"""Factory instrumentation."""
from __future__ import annotations
import functools
import logging
from typing import Any, Callable
from novamind.observability import metrics as prom
from novamind.observability.tracer import set_span_attribute, start_span

logger = logging.getLogger("novamind.observability.integrations.factory")


def trace_agent_load(get_fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(get_fn)
    def wrapper(self: Any, name: str) -> Any:
        with start_span("factory.get", {"agent": name}):
            try:
                agent = get_fn(self, name)
                set_span_attribute("novamind.agent.loaded", agent is not None)
                if agent is not None:
                    try:
                        role = self.get_role(name)
                        set_span_attribute("novamind.agent.role", role)
                    except Exception:
                        pass
                return agent
            except Exception as e:
                set_span_attribute("novamind.error", type(e).__name__)
                prom.record_agent_error(name, type(e).__name__)
                raise
    return wrapper


def trace_get_role(get_role_fn: Callable[..., str]) -> Callable[..., str]:
    @functools.wraps(get_role_fn)
    def wrapper(self: Any, name: str) -> str:
        with start_span("factory.get_role", {"agent": name}):
            result = get_role_fn(self, name)
            set_span_attribute("novamind.agent.role", result)
            return result
    return wrapper


def instrument_factory(factory_instance: Any) -> Any:
    if getattr(factory_instance, "_observability_instrumented", False):
        return factory_instance
    cls = type(factory_instance)
    if not getattr(cls, "_observability_instrumented", False):
        cls.get = trace_agent_load(cls.get)
        cls.get_role = trace_get_role(cls.get_role)
        cls._observability_instrumented = True
    factory_instance._observability_instrumented = True
    logger.info("Factory instrumented")
    return factory_instance


__all__ = ["instrument_factory", "trace_agent_load"]
