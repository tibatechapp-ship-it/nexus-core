"""LLM Router instrumentation."""
from __future__ import annotations
import functools
import logging
from typing import Any, Callable, Optional
from novamind.observability import metrics as prom
from novamind.observability.tracer import set_span_attribute, start_span

logger = logging.getLogger("novamind.observability.integrations.llm_router")


DEFAULT_PRICING = {
    "zai/glm-4": (1.0, 1.0),
    "zai/glm-4-plus": (5.0, 5.0),
    "openai/gpt-4": (30.0, 60.0),
    "openai/gpt-4-turbo": (10.0, 30.0),
    "openai/gpt-3.5-turbo": (0.5, 1.5),
    "anthropic/claude-3-opus": (15.0, 75.0),
    "anthropic/claude-3-sonnet": (3.0, 15.0),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "groq/llama-3.1-70b": (0.59, 0.79),
    "groq/llama-3.1-8b": (0.05, 0.08),
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int, pricing: Optional[dict] = None) -> float:
    table = pricing or DEFAULT_PRICING
    key = f"{provider}/{model}"
    if key not in table:
        for k, v in table.items():
            if model.startswith(k.split("/")[-1]):
                input_price, output_price = v
                break
        else:
            return 0.0
    else:
        input_price, output_price = table[key]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def record_llm_call(provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0, latency: float = 0.0, pricing: Optional[dict] = None) -> dict:
    prom.record_llm_tokens(provider, model, input_tokens, output_tokens)
    cost = estimate_cost(provider, model, input_tokens, output_tokens, pricing)
    if cost > 0:
        prom.record_cost(provider, cost)
    set_span_attribute("llm.provider", provider)
    set_span_attribute("llm.model", model)
    set_span_attribute("llm.input_tokens", input_tokens)
    set_span_attribute("llm.output_tokens", output_tokens)
    set_span_attribute("llm.latency_seconds", latency)
    set_span_attribute("llm.cost_usd", cost)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}


def _extract_usage(result: Any) -> tuple:
    provider = ""
    model = ""
    input_tokens = 0
    output_tokens = 0
    if isinstance(result, dict):
        provider = result.get("provider", "")
        model = result.get("model", "")
        usage = result.get("usage", {}) or {}
        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    else:
        provider = getattr(result, "provider", "")
        model = getattr(result, "model", "")
        usage = getattr(result, "usage", None)
        if usage:
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
                output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            else:
                input_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0)
                output_tokens = getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0)
    return provider, model, int(input_tokens or 0), int(output_tokens or 0)


def trace_llm_call(call_fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(call_fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        import time
        start = time.monotonic()
        with start_span("llm.call"):
            try:
                result = call_fn(*args, **kwargs)
                latency = time.monotonic() - start
                provider, model, input_tokens, output_tokens = _extract_usage(result)
                if provider and model:
                    record_llm_call(provider, model, input_tokens, output_tokens, latency)
                return result
            except Exception as e:
                set_span_attribute("llm.error", type(e).__name__)
                raise
    return wrapper


def instrument_llm_router(router_instance: Any) -> Any:
    if getattr(router_instance, "_observability_instrumented", False):
        return router_instance
    for method_name in ("call", "complete", "chat", "generate"):
        if hasattr(router_instance, method_name):
            original = getattr(router_instance, method_name)
            if callable(original):
                setattr(router_instance, method_name, trace_llm_call(original))
                logger.info("Instrumented LLM router method: %s", method_name)
    router_instance._observability_instrumented = True
    return router_instance


__all__ = ["instrument_llm_router", "record_llm_call", "trace_llm_call", "estimate_cost", "DEFAULT_PRICING"]
