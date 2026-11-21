"""Tracer — OpenTelemetry wrapper with graceful degradation.

إذا لم تكن OpenTelemetry مثبتة، يعمل في "no-op" mode.
"""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from novamind.observability import context as ctx
from novamind.observability.config import get_config

logger = logging.getLogger("novamind.observability.tracer")


# ═══ Try import OpenTelemetry ═══
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    otel_trace = None  # type: ignore


# ═══ Global tracer ═══
_tracer: Optional[Any] = None
_initialized = False


def _init_otel() -> None:
    """Initialize OpenTelemetry (once)."""
    global _tracer, _initialized
    if _initialized or not _OTEL_AVAILABLE:
        return

    cfg = get_config()
    if not cfg.tracing_enabled:
        _initialized = True
        return

    resource = Resource.create({
        "service.name": cfg.service_name,
        "service.version": cfg.service_version,
    })
    provider = TracerProvider(resource=resource)

    # Exporter selection. Pytest and some ASGI servers temporarily replace
    # sys.stdout; the BatchSpanProcessor exports asynchronously, after those
    # capture streams may already be closed. Bind console output to the stable
    # interpreter stream instead of the transient captured sys.stdout.
    if cfg.exporter == "console":
        stable_stream = getattr(sys, "__stdout__", None)
        if stable_stream is not None and not getattr(stable_stream, "closed", False):
            provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter(out=stable_stream))
            )
        else:
            logger.warning(
                "Console tracing disabled: stable stdout is unavailable; "
                "use exporter='otlp' or exporter='none'."
            )
    elif cfg.exporter == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.otlp_endpoint))
            )
        except ImportError:
            logger.warning("OTLP exporter unavailable — falling back to stable console")
            stable_stream = getattr(sys, "__stdout__", None)
            if stable_stream is not None and not getattr(stable_stream, "closed", False):
                provider.add_span_processor(
                    BatchSpanProcessor(ConsoleSpanExporter(out=stable_stream))
                )

    otel_trace.set_tracer_provider(provider)
    _tracer = otel_trace.get_tracer(cfg.service_name, cfg.service_version)
    _initialized = True
    logger.info("OpenTelemetry initialized (exporter=%s)", cfg.exporter)


@contextmanager
def start_span(
    name: str,
    attributes: Optional[dict] = None,
    kind: str = "internal",
) -> Iterator[Any]:
    """Context manager for starting a span.

    Usage:
        with start_span("my.operation", {"key": "value"}) as span:
            ...
    """
    _init_otel()

    # Trace context management
    parent_span = ctx.current_span_id()
    if not ctx.current_trace_id():
        ctx.set_trace_id(ctx.new_trace_id())
    span_id = ctx.new_span_id()

    token_span = ctx._span_id.set(span_id)
    token_parent = ctx._parent_span_id.set(parent_span)
    token_attrs = ctx._attributes.set(dict(attributes or {}))

    span = None
    try:
        if _tracer is not None:
            span = _tracer.start_span(name)
            if attributes:
                for k, v in attributes.items():
                    try:
                        span.set_attribute(k, v)
                    except Exception:
                        pass
            span.set_attribute("novamind.trace_id", ctx.current_trace_id() or "")
            span.set_attribute("novamind.span_id", span_id)
            if parent_span:
                span.set_attribute("novamind.parent_span_id", parent_span)

        yield span
    finally:
        if span is not None:
            span.end()
        ctx._span_id.reset(token_span)
        ctx._parent_span_id.reset(token_parent)
        ctx._attributes.reset(token_attrs)


def set_span_attribute(key: str, value: Any) -> None:
    """Set attribute on current span (if any)."""
    ctx.set_attribute(key, value)
    if _tracer is None:
        return
    span = otel_trace.get_current_span() if _OTEL_AVAILABLE else None
    if span is not None:
        try:
            span.set_attribute(key, value)
        except Exception:
            pass


def is_enabled() -> bool:
    """Is tracing enabled and available?"""
    return _OTEL_AVAILABLE and get_config().tracing_enabled


def shutdown() -> None:
    """Flush and shut down the process-wide provider at application exit.

    OpenTelemetry's global TracerProvider cannot be replaced after registration.
    Keep initialization latched after shutdown so later spans do not attempt to
    register a second provider against the already-locked global API.
    """
    global _tracer
    if not _OTEL_AVAILABLE or _tracer is None:
        return

    try:
        provider = otel_trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=5000)
        shutdown_provider = getattr(provider, "shutdown", None)
        if callable(shutdown_provider):
            shutdown_provider()
    except Exception:
        logger.exception("OpenTelemetry provider shutdown failed")
    finally:
        _tracer = None
        # _initialized remains True: the process-global provider is one-shot.


__all__ = ["start_span", "set_span_attribute", "is_enabled", "shutdown"]
