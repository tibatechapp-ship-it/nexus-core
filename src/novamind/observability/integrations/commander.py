"""Commander instrumentation."""
from __future__ import annotations
import functools
import logging
from typing import Any, Callable, Optional
from novamind.observability import context as ctx
from novamind.observability import metrics as prom
from novamind.observability.tracer import set_span_attribute, start_span

logger = logging.getLogger("novamind.observability.integrations.commander")


def trace_pipeline_selection(choose_fn: Callable[..., str]) -> Callable[..., str]:
    @functools.wraps(choose_fn)
    def wrapper(self: Any, task: str) -> str:
        with start_span("commander.choose_pipeline", {"task": str(task)[:200]}):
            result = choose_fn(self, task)
            set_span_attribute("novamind.pipeline_id", result)
            return result
    return wrapper


def trace_execute(execute_fn: Callable[..., dict]) -> Callable[..., dict]:
    @functools.wraps(execute_fn)
    def wrapper(self: Any, task: str, pipeline_id: Optional[str] = None) -> dict:
        with start_span("commander.execute", {"task": str(task)[:200], "pipeline_id": pipeline_id or "auto"}):
            ctx.set_task(task)
            try:
                effective_pipeline = pipeline_id
                if effective_pipeline is None:
                    effective_pipeline = self.choose_pipeline(task)
                set_span_attribute("novamind.pipeline", effective_pipeline)
                with prom.time_pipeline(effective_pipeline):
                    result = execute_fn(self, task, pipeline_id)
                set_span_attribute("novamind.result.ok", True)
                return result
            except Exception as e:
                set_span_attribute("novamind.result.ok", False)
                set_span_attribute("novamind.error", type(e).__name__)
                prom.record_agent_error("commander", type(e).__name__)
                raise
    return wrapper


def instrument_commander(commander_cls: type) -> type:
    if getattr(commander_cls, "_observability_instrumented", False):
        logger.debug("Commander already instrumented")
        return commander_cls
    commander_cls.choose_pipeline = trace_pipeline_selection(commander_cls.choose_pipeline)
    commander_cls.execute = trace_execute(commander_cls.execute)
    commander_cls._observability_instrumented = True
    logger.info("Commander instrumented")
    return commander_cls


__all__ = ["instrument_commander", "trace_execute", "trace_pipeline_selection"]
