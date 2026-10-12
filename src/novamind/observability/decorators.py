"""Decorators — @traced, @metered, @timed."""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional, TypeVar

from novamind.observability import metrics as prom
from novamind.observability.tracer import start_span

logger = logging.getLogger("novamind.observability.decorators")

F = TypeVar("F", bound=Callable[..., Any])


def traced(name: Optional[str] = None, attributes: Optional[dict] = None) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        span_name = name or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attrs = dict(attributes or {})
            attrs["function"] = fn.__qualname__
            with start_span(span_name, attrs):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def metered(metric: str = "agent_calls", **labels: Any) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if metric == "agent_calls":
                agent = labels.get("agent", fn.__qualname__)
                try:
                    result = fn(*args, **kwargs)
                    prom.record_agent_call(agent, status="success")
                    return result
                except Exception as e:
                    prom.record_agent_call(agent, status="error")
                    prom.record_agent_error(agent, type(e).__name__)
                    raise

            if metric == "agent_errors":
                agent = labels.get("agent", fn.__qualname__)
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    prom.record_agent_error(agent, type(e).__name__)
                    raise

            if metric == "active_agents":
                prom.inc_active_agents()
                try:
                    return fn(*args, **kwargs)
                finally:
                    prom.dec_active_agents()

            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def timed(fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.monotonic() - start
            logger.debug("%s took %.3fs", fn.__qualname__, elapsed)

    return wrapper  # type: ignore[return-value]


__all__ = ["traced", "metered", "timed"]
