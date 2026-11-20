"""Compatibility LLM wrapper with explicit, opt-in simulation only."""
from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable

from novamind.adapters.router_adapter import wrap_router

logger = logging.getLogger(__name__)
_SENTINEL = object()


def _load_router():
    """Load the canonical router only when at least one real provider exists."""
    try:
        from novamind.core.llm_router import get_router

        router = get_router()
        return router if getattr(router, "providers", None) else None
    except Exception as exc:
        logger.warning("Could not load canonical LLM router: %s", type(exc).__name__)
        return None


def is_llm_available() -> bool:
    """Return whether a real provider is configured."""
    router = _load_router()
    return bool(router and getattr(router, "providers", None))


def _normalize_prompt(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        parts = []
        if prompt.get("system"):
            parts.append(f"[system] {prompt['system']}")
        if prompt.get("user"):
            parts.append(str(prompt["user"]))
        return "\n".join(parts) if parts else str(prompt)
    return str(prompt)


def _extract_provider(response: Any) -> str:
    if isinstance(response, dict):
        for key in ("provider", "provider_name", "source"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
        for nested_key in ("metadata", "raw_response", "data"):
            nested = response.get(nested_key)
            if isinstance(nested, dict):
                for key in ("provider", "provider_name", "source"):
                    value = nested.get(key)
                    if isinstance(value, str) and value:
                        return value
    elif response is not None:
        for attr in ("provider", "provider_name", "source"):
            value = getattr(response, attr, None)
            if isinstance(value, str) and value:
                return value
    return ""


def _failure(model: str, message: str) -> dict:
    return {
        "ok": False,
        "simulated": False,
        "text": "",
        "model": model,
        "provider": "none",
        "error": message[:300],
        "raw": {},
    }


def _mock(model: str, prompt: str) -> dict:
    return {
        "ok": True,
        "simulated": True,
        "text": f"[MOCK] Response to: {prompt[:50]}...",
        "model": model,
        "provider": "mock-provider",
        "raw": {},
    }


def make_llm_call(
    *,
    router: Any = _SENTINEL,
    model: str = "default",
    timeout: float | None = None,
    max_retries: int = 0,
    fallback_to_mock: bool = False,
    **kwargs,
) -> Callable[[Any], Awaitable[dict]]:
    """Create an async callable; mocks require explicit fallback_to_mock=True."""
    if router is _SENTINEL:
        resolved_router = _load_router()
    else:
        # Explicit None means no router; it never triggers hidden global lookup.
        resolved_router = router

    async def call_fn(prompt: Any) -> dict:
        normalized_prompt = _normalize_prompt(prompt)
        if resolved_router is None:
            if fallback_to_mock:
                return _mock(model, normalized_prompt)
            return _failure(model, "no real LLM provider configured")

        adapter = wrap_router(resolved_router)
        try:
            response = adapter.generate(
                normalized_prompt,
                model=model,
                timeout=timeout,
                **kwargs,
            )
            if inspect.isawaitable(response):
                response = await response
            if isinstance(response, dict):
                if response.get("ok") is False:
                    message = str(response.get("error") or "provider request failed")
                    if fallback_to_mock:
                        return _mock(model, normalized_prompt)
                    return _failure(model, message)
                text = response.get("text", "")
                provider = _extract_provider(response) or "unknown"
                actual_model = response.get("model") or model
                if response.get("simulated") or provider.lower() in {
                    "mock", "mock-provider", "offline"
                }:
                    if fallback_to_mock:
                        return _mock(model, normalized_prompt)
                    return _failure(model, "simulated provider response rejected")
                if provider == "unknown":
                    return _failure(model, "router response did not identify the real provider")
            else:
                return _failure(model, "router returned an unstructured response without provider metadata")

            if not isinstance(text, str) or not text.strip():
                return _failure(model, "provider returned an empty response")
            return {
                "ok": True,
                "simulated": False,
                "text": text,
                "model": actual_model,
                "provider": provider,
                "raw": response,
            }
        except Exception as exc:
            logger.exception("Canonical router call failed")
            if fallback_to_mock:
                return _mock(model, normalized_prompt)
            return _failure(model, f"{type(exc).__name__}: {exc}")

    return call_fn


__all__ = [
    "make_llm_call",
    "is_llm_available",
]
