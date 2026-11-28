"""Factory LLM Wrapper — ربط Factory بـ LLMRouter الحقيقي."""

from __future__ import annotations
from typing import Any, Callable, Dict
import asyncio
import inspect
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


def _enabled_providers(router: Any) -> list[str]:
    """Return enabled provider names; an empty router means LLM is unavailable."""
    if router is None:
        return []
    providers = getattr(router, "providers", None)
    if isinstance(providers, dict):
        candidates = list(providers.values())
    elif isinstance(providers, (list, tuple, set)):
        candidates = list(providers)
    else:
        return []
    names: list[str] = []
    for provider in candidates:
        if not getattr(provider, "enabled", True):
            continue
        name = getattr(provider, "name", None)
        if name:
            names.append(str(name))
    return names


def is_llm_available() -> bool:
    return bool(_enabled_providers(_load_router()))


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
    fallback_to_mock: bool = False,
    router: Any = None,
) -> Callable:
    """يبني llm_call(prompt_dict) -> dict.

    Signature المتوافق مع LLMRouter.generate الحقيقي:
        generate(prompt, system="", role="fast", temperature=0.2,
                 max_tokens=None, provider=None, allow_fallback=True) -> dict

    الوضع الافتراضي fail-closed: لا.mock، لا استجابة فارغة، ولا مزود مُفعّل = خطأ.
    """

    async def _llm_call(prompt: Dict[str, str]) -> Dict[str, Any]:
        started = time.time()
        if not isinstance(prompt, dict):
            prompt = {"user": str(prompt)}
        active_router = router if router is not None else _load_router()
        system = prompt.get("system", "")
        user = prompt.get("user", "")
        model = prompt.get("model", "auto")
        role = prompt.get("role", "fast")
        if role not in {"fast", "smart"}:
            role = "fast"
        provider = prompt.get("provider") or None
        allow_fallback = bool(prompt.get("allow_fallback", True))

        try:
            temperature = float(prompt.get("temperature", 0.2))
        except (TypeError, ValueError):
            temperature = 0.2
        max_tokens: int | None = None
        max_tokens_raw = prompt.get("max_tokens")
        if max_tokens_raw is not None:
            try:
                max_tokens = int(max_tokens_raw)
            except (TypeError, ValueError):
                max_tokens = None

        if not _enabled_providers(active_router):
            if fallback_to_mock:
                return {
                    "text": f"[MOCK] {user[:200]}",
                    "tokens": 0,
                    "provider": "mock",
                    "duration_ms": 0,
                    "error": "لا يوجد مزود لغوي مُفعّل؛ تم السماح بـ mock صراحةً",
                }
            return {
                "text": "",
                "tokens": 0,
                "provider": "none",
                "duration_ms": int((time.time() - started) * 1000),
                "error": "لا يوجد مزود لغوي مُفعّل (fail-closed)",
                "attempts": 0,
            }

        last_error = None
        limiter = get_limiter()
        for attempt in range(max_retries + 1):
            # ── Rate limit check ──
            try:
                await limiter.wait_if_needed(
                    str(provider or "default"),
                    tokens_estimate=2000,
                    max_wait=min(5.0, float(timeout) / 4),
                )
            except Exception:
                pass

            try:
                kwargs = {
                    "system": system,
                    "role": role,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "provider": provider,
                    "allow_fallback": allow_fallback,
                }
                if inspect.iscoroutinefunction(active_router.generate):
                    response = await active_router.generate(user, **kwargs)
                else:
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(
                        None, lambda: active_router.generate(user, **kwargs)
                    )
                if inspect.isawaitable(response):
                    response = await response

                if isinstance(response, dict):
                    if response.get("ok") is not True:
                        raise RuntimeError(response.get("error") or "فشل المزود")
                    text = response.get("text") or ""
                    used_provider = response.get("provider") or _detect_provider(active_router)
                else:
                    text = response
                    used_provider = _detect_provider(active_router)
                if text is None:
                    text = ""
                if not isinstance(text, str):
                    text = str(text)
                if not text.strip():
                    raise RuntimeError("استجابة فارغة من المزود (fail-closed)")

                if _is_mock_response(text, str(model), str(used_provider)):
                    return {
                        "text": "",
                        "tokens": 0,
                        "provider": used_provider,
                        "duration_ms": int((time.time() - started) * 1000),
                        "error": "نموذج/Mock محظور؛ لا يُستخدم في المسار الحقيقي",
                        "attempts": attempt + 1,
                    }

                tokens_used = _estimate_tokens(text)
                limiter.record(str(used_provider), tokens_used)
                _duration = int((time.time() - started) * 1000)

                # سجّل التكلفة (non-blocking)
                if _record_cost is not None:
                    try:
                        _record_cost(
                            provider=used_provider,
                            tokens=tokens_used,
                            duration_ms=_duration,
                            agent_id=prompt.get("agent_id"),
                            task_id=prompt.get("task_id"),
                            success=True,
                        )
                    except Exception:
                        pass

                return {
                    "text": text,
                    "tokens": tokens_used,
                    "provider": used_provider,
                    "duration_ms": _duration,
                    "attempts": attempt + 1,
                }
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


def _is_mock_response(text: str, model: str, provider: str) -> bool:
    """True when a response is explicitly synthetic, never a real provider answer."""
    lowered_model = model.casefold()
    lowered_provider = provider.casefold()
    return (
        text.startswith("[MOCK]")
        or lowered_model.startswith("mock")
        or lowered_provider in {"mock", "none"}
    )


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
