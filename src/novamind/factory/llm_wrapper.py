"""Factory LLM Wrapper — ربط Factory بـ LLMRouter الحقيقي."""
from __future__ import annotations
from typing import Dict, Any, Optional, Callable
import asyncio
import time
from novamind.factory.rate_limiter import get_limiter
try:
    from novamind.core.hive.analytics.cost_tracker import record_cost as _record_cost
except Exception:
    _record_cost = None



_router_cache: Dict[str, Any] = {}


def _load_router():
    """يحمل LLMRouter (singleton)."""
    if "router" in _router_cache:
        return _router_cache["router"]
    try:
        from novamind.core.llm_router import LLMRouter
        router = LLMRouter()
        _router_cache["router"] = router
        return router
    except Exception as e:
        _router_cache["error"] = str(e)
        return None


def is_llm_available() -> bool:
    return _load_router() is not None


def list_providers() -> list:
    router = _load_router()
    if not router:
        return []
    try:
        providers = getattr(router, "providers", None)
        if isinstance(providers, dict):
            return list(providers.keys())
        elif isinstance(providers, list):
            return [getattr(p, "name", str(p)) for p in providers]
        return []
    except Exception:
        return []


def make_llm_call(
    timeout: int = 60,
    max_retries: int = 2,
    fallback_to_mock: bool = True,
) -> Callable:
    """يبني llm_call(prompt_dict) -> dict.

    Signature متوافق مع LLMRouter.generate:
        generate(prompt, system_prompt='', timeout=60) -> str
    """

    async def _llm_call(prompt: Dict[str, str]) -> Dict[str, Any]:
        started = time.time()
        router = _load_router()
        provider = None  # ← جديد: يُحدَّد لاحقاً من router

        if not router:
            if fallback_to_mock:
                return {
                    "text": f"[MOCK] {prompt.get('user', '')[:200]}",
                    "tokens": 0,
                    "provider": "mock",
                    "duration_ms": 0,
                    "error": "LLM Router غير متاح",
                }
            return {"text": "", "tokens": 0, "provider": "none", "error": "no router"}

        system = prompt.get("system", "")
        user = prompt.get("user", "")

        last_error = None
        limiter = get_limiter()
        for attempt in range(max_retries + 1):
            # ── Rate limit check ──
            try:
                await limiter.wait_if_needed(
                    provider or "default",
                    tokens_estimate=2000,
                    max_wait=min(5.0, float(timeout) / 4),
                )
            except Exception:
                pass

            try:
                # جرب async أولًا، ثم sync
                import inspect as _inspect
                is_async = _inspect.iscoroutinefunction(router.generate)

                if is_async:
                    # async
                    text = await router.generate(
                        prompt=user,
                        system_prompt=system,
                        timeout=float(timeout),
                    )
                else:
                    # sync
                    loop = asyncio.get_event_loop()
                    text = await loop.run_in_executor(
                        None,
                        lambda: router.generate(
                            prompt=user,
                            system_prompt=system,
                            timeout=float(timeout),
                        ),
                    )
                if text and isinstance(text, str) and text.strip():
                    tokens_used = _estimate_tokens(text)
                    limiter.record(provider or "default", tokens_used)
                    _duration = int((time.time() - started) * 1000)
                    _provider = _detect_provider(router)

                    # سجّل التكلفة (non-blocking)
                    if _record_cost is not None:
                        try:
                            _agent = prompt.get("agent_id") if isinstance(prompt, dict) else None
                            _task = prompt.get("task_id") if isinstance(prompt, dict) else None
                            _record_cost(
                                provider=_provider,
                                tokens=tokens_used,
                                duration_ms=_duration,
                                agent_id=_agent,
                                task_id=_task,
                                success=True,
                            )
                        except Exception:
                            pass

                    return {
                        "text": text,
                        "tokens": tokens_used,
                        "provider": _provider,
                        "duration_ms": _duration,
                        "attempts": attempt + 1,
                    }
                last_error = "empty response"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"

            if attempt < max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))

        return {
            "text": "",
            "tokens": 0,
            "provider": "auto",
            "duration_ms": int((time.time() - started) * 1000),
            "error": last_error or "failed after retries",
            "attempts": max_retries + 1,
        }

    return _llm_call


def _estimate_tokens(text: str) -> int:
    """تقدير tokens (4 حروف ≈ token)."""
    return max(1, len(text) // 4)


def _detect_provider(router: Any) -> str:
    """يحاول كشف المزوّد النشط."""
    try:
        # 1. الأولوية لـ last_provider (اللي LLMRouter بيحدّثه فعلاً)
        lp = getattr(router, "last_provider", None)
        if lp:
            return lp
        # 2. fallback: first provider with fail_count=0
        fc = getattr(router, "fail_counts", None)
        if isinstance(fc, dict) and fc:
            for name, count in fc.items():
                if count == 0:
                    return name
            return list(fc.keys())[0]
    except Exception:
        pass
    return "auto"


def get_router():
    """Alias للتوافق مع الكود القديم."""
    return _load_router()
