"""NovaMind Observability — unified API.

Provides:
- OpenTelemetry tracing (traced, start_span)
- Prometheus metrics (metrics)
- ContextVar propagation (context)
- Decorators (@traced, @metered, @timed)
"""
from __future__ import annotations

from novamind.observability import context, metrics
from novamind.observability.config import get_config
from novamind.observability.decorators import metered, timed, traced
from novamind.observability.tracer import is_enabled, set_span_attribute, start_span

__all__ = [
    "context",
    "metrics",
    "get_config",
    "start_span",
    "set_span_attribute",
    "is_enabled",
    "traced",
    "metered",
    "timed",
]

__version__ = "3.3.0"
