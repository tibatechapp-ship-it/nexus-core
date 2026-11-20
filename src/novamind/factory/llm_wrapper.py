"""Factory LLM wrapper — real-provider calls with explicit failure semantics."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict

from novamind.adapters.router_adapter import wrap_router
from novamind.factory.rate_limiter import get_limiter

try:
    from novamind.core.hive.analytics.cost_tracker import record_cost as _record_cost
except Exception:
    _record_cost = None

logger = logging.getLogger(__name__)
_router_cache: Dict[str, Any] = {}


def _load_router():
    """Return a configured real router; an empty router is unavailable."""
    cached = _router_cache.get("router")
    if cached is not None and getattr(cached, "providers", None):
        return cached
    try:
        from novamind.core.llm_router import get_router

        router = get_router()
        if getattr(router, "providers", None):
            _router_cache["router"] = router
            _router_cache.pop("error", None)
            return router
        _router_cache.pop("router", None)
        return None
    except Exception as exc:
        _router_cache["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Could not load configured LLM router: %s", type(exc).__name__)
        return None


def is_llm_available() -> bool:
    """True only when at least one real provider is configured."""
    router = _load_router()
    return bool(router and getattr(router, "providers", None))


def list_providers() -> list:
    router = _load_router()
    if router is None:
        return []
    return [getattr(provider, "name", str(provider)) for provider in router.providers]


def _mock_result(prompt: str, model: str, duration_ms: int = 0) -> Dict[str, Any]:
    """Explicitly opted-in test result; never confused with a real provider."""
    return {
        "ok": True,
        "simulated": True,
        "text": f"[MOCK] {prompt[:200]}",
        "tokens": 0,
        "provider": "mock",
        "model": model,
        "duration_ms": duration_ms,
        "attempts": 0,
    }


def make_llm_call(
    timeout: int = 60,
    max_retries: int = 2,
    fallback_to_mock: bool = False,
) -> Callable:
    """Build an async callable. Mock fallback is disabled unless explicitly requested."""

    async def _llm_call(prompt: Dict[str, str]) -> Dict[str, Any]:
        started = time.time()
        system = prompt.get("system", "") if isinstance(prompt, dict) else ""
        user = prompt.get("user", "") if isinstance(prompt, dict) else str(prompt)
        model = "fast"
        router = _load_router()

        if router is None:
            if fallback_to_mock:
                return _mock_result(user, model, int((time.time() - started) * 1000))
            return {
                "ok": False,
                "simulated": False,
                "text": "",
                "tokens": 0,
                "provider": "none",
                "model": "",
                "duration_ms": int((time.time() - started) * 1000),
                "error": "no real LLM provider configured",
                "attempts": 0,
            }

        adapter = wrap_router(router)
        limiter = get_limiter()
        last_error = "provider returned no usable text"

        for attempt in range(max_retries + 1):
            try:
                await limiter.wait_if_needed(
                    "configured",
                    tokens_estimate=2000,
                    max_wait=min(5.0, float(timeout) / 4),
                )
            except Exception as exc:
                logger.warning("LLM rate limiter unavailable: %s", type(exc).__name__)

            try:
                response = await asyncio.to_thread(
                    adapter.generate,
                    user,
                    model=model,
                    timeout=timeout,
                    system=system,
                )
                if isinstance(response, dict):
                    if response.get("ok") is False:
                        last_error = str(response.get("error") or "provider request failed")
                        raise RuntimeError(last_error)
                    text = response.get("text") or ""
                    provider = response.get("provider") or "unknown"
                    model_name = response.get("model") or model
                    if response.get("simulated") or str(provider).lower() in {
                        "mock", "mock-provider", "offline"
                    }:
                        raise RuntimeError("simulated provider response rejected")
                else:
                    text = str(response or "")
                    provider = "unknown"
                    model_name = model

                if not isinstance(text, str) or not text.strip():
                    last_error = "provider returned an empty response"
                    raise RuntimeError(last_error)

                tokens_used = max(1, len(text) // 4)
                duration_ms = int((time.time() - started) * 1000)
                try:
                    limiter.record(provider, tokens_used)
                except Exception as exc:
                    logger.warning("LLM usage limiter update failed: %s", type(exc).__name__)

                if _record_cost is not None:
                    try:
                        _record_cost(
                            provider=provider,
                            tokens=tokens_used,
                            duration_ms=duration_ms,
                            agent_id=prompt.get("agent_id") if isinstance(prompt, dict) else None,
                            task_id=prompt.get("task_id") if isinstance(prompt, dict) else None,
                            success=True,
                        )
                    except Exception:
                        logger.exception("Could not record LLM cost telemetry")

                return {
                    "ok": True,
                    "simulated": False,
                    "text": text,
                    "tokens": tokens_used,
                    "provider": provider,
                    "model": model_name,
                    "duration_ms": duration_ms,
                    "attempts": attempt + 1,
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("LLM request attempt %s failed: %s", attempt + 1, last_error[:200])
                if attempt < max_retries:
                    await asyncio.sleep(min(2.0, 0.5 * (attempt + 1)))

        duration_ms = int((time.time() - started) * 1000)
        if fallback_to_mock:
            return _mock_result(user, model, duration_ms)
        return {
            "ok": False,
            "simulated": False,
            "text": "",
            "tokens": 0,
            "provider": "none",
            "model": "",
            "duration_ms": duration_ms,
            "error": last_error,
            "attempts": max_retries + 1,
        }

    return _llm_call


def _estimate_tokens(text: str) -> int:
    """Rough local estimate; provider usage should replace it when available."""
    return max(1, len(text) // 4)


def _detect_provider(router: Any) -> str:
    """Best-effort active provider lookup for legacy integrations."""
    last_provider = getattr(router, "last_provider", None)
    if isinstance(last_provider, str) and last_provider:
        return last_provider
    return "unknown"


def get_router():
    """Compatibility alias for the configured router."""
    return _load_router()
