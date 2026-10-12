"""Exporters — Console + OTLP + Null for OpenTelemetry."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("novamind.observability.exporters")


def make_console_exporter() -> Optional[Any]:
    try:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        return ConsoleSpanExporter()
    except ImportError:
        return None


def make_otlp_exporter(endpoint: str = "http://localhost:4317") -> Optional[Any]:
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        return OTLPSpanExporter(endpoint=endpoint)
    except ImportError as e:
        logger.warning("OTLP exporter unavailable: %s", e)
        return None


def make_null_exporter() -> Optional[Any]:
    try:
        from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

        class _NullExporter(SpanExporter):
            def export(self, spans):  # type: ignore[no-untyped-def]
                return SpanExportResult.SUCCESS

            def shutdown(self) -> None:
                pass

        return _NullExporter()
    except ImportError:
        return None


def make_exporter(kind: str, endpoint: str = "http://localhost:4317") -> Optional[Any]:
    kind = (kind or "console").lower()
    if kind == "console":
        return make_console_exporter()
    if kind == "otlp":
        return make_otlp_exporter(endpoint)
    if kind == "none":
        return make_null_exporter()
    return make_console_exporter()


__all__ = ["make_console_exporter", "make_otlp_exporter", "make_null_exporter", "make_exporter"]
