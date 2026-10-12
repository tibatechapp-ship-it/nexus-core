"""Metrics — Prometheus registry for NovaMind."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("novamind.observability.metrics")

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False
    CollectorRegistry = None  # type: ignore

_registry: Optional[Any] = None
_metrics: dict = {}


def _init_metrics() -> None:
    global _registry, _metrics
    if _metrics or not _PROM_AVAILABLE:
        return

    _registry = CollectorRegistry()
    _metrics = {
        "agent_calls": Counter(
            "novamind_agent_calls_total",
            "Total agent calls",
            ["agent", "status"],
            registry=_registry,
        ),
        "llm_tokens": Counter(
            "novamind_llm_tokens_total",
            "Total LLM tokens",
            ["provider", "model", "direction"],
            registry=_registry,
        ),
        "pipeline_duration": Histogram(
            "novamind_pipeline_duration_seconds",
            "Pipeline execution duration",
            ["pipeline"],
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
            registry=_registry,
        ),
        "agent_errors": Counter(
            "novamind_agent_errors_total",
            "Total agent errors",
            ["agent", "error_type"],
            registry=_registry,
        ),
        "cost_usd": Counter(
            "novamind_cost_usd_total",
            "Total cost in USD",
            ["provider"],
            registry=_registry,
        ),
        "active_agents": Gauge(
            "novamind_active_agents",
            "Number of active agents",
            registry=_registry,
        ),
    }
    logger.info("Prometheus metrics initialized")


def record_agent_call(agent: str, status: str = "success") -> None:
    _init_metrics()
    if "agent_calls" in _metrics:
        _metrics["agent_calls"].labels(agent=agent, status=status).inc()


def record_llm_tokens(provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    _init_metrics()
    if "llm_tokens" in _metrics:
        m = _metrics["llm_tokens"]
        if input_tokens:
            m.labels(provider=provider, model=model, direction="input").inc(input_tokens)
        if output_tokens:
            m.labels(provider=provider, model=model, direction="output").inc(output_tokens)


def record_agent_error(agent: str, error_type: str) -> None:
    _init_metrics()
    if "agent_errors" in _metrics:
        _metrics["agent_errors"].labels(agent=agent, error_type=error_type).inc()


def record_cost(provider: str, usd: float) -> None:
    _init_metrics()
    if "cost_usd" in _metrics and usd > 0:
        _metrics["cost_usd"].labels(provider=provider).inc(usd)


@contextmanager
def time_pipeline(pipeline: str) -> Iterator[None]:
    _init_metrics()
    start = time.monotonic()
    try:
        yield
    finally:
        if "pipeline_duration" in _metrics:
            _metrics["pipeline_duration"].labels(pipeline=pipeline).observe(time.monotonic() - start)


def set_active_agents(count: int) -> None:
    _init_metrics()
    if "active_agents" in _metrics:
        _metrics["active_agents"].set(count)


def inc_active_agents(delta: int = 1) -> None:
    _init_metrics()
    if "active_agents" in _metrics:
        _metrics["active_agents"].inc(delta)


def dec_active_agents(delta: int = 1) -> None:
    _init_metrics()
    if "active_agents" in _metrics:
        _metrics["active_agents"].dec(delta)


def export_prometheus() -> tuple:
    _init_metrics()
    if not _PROM_AVAILABLE or _registry is None:
        return b"# prometheus_client not available\n", "text/plain"
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def snapshot() -> dict:
    _init_metrics()
    return {"available": _PROM_AVAILABLE, "metrics_count": len(_metrics), "metric_names": list(_metrics.keys())}


def reset() -> None:
    global _registry, _metrics
    _registry = None
    _metrics = {}


__all__ = [
    "record_agent_call", "record_llm_tokens", "record_agent_error",
    "record_cost", "time_pipeline", "set_active_agents",
    "inc_active_agents", "dec_active_agents",
    "export_prometheus", "snapshot", "reset",
]
