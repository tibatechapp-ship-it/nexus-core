"""
Router Adapter — يحوّل استدعاءات pipeline → NovaMind.router.

pipeline يستخدم: router.generate(prompt, model=..., timeout=...)
Router الحقيقي: router.generate(prompt, system=..., role=...)

هذا الملف يربط بينهما.
"""

from __future__ import annotations
import logging
import inspect
from typing import Any, Dict, Optional

logger = logging.getLogger("novamind.adapters.router_adapter")


class RouterAdapter:
    """
    Adapter يحوّل signature القديم → الجديد.

    يُعيد دائماً dict بالشكل:
        {
            "text": "...",
            "provider": "...",
            "model": "...",
        }
    """

    def __init__(self, router):
        self._router = router
        self._warned = False

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        system: str = "",
        **kwargs,
    ):
        """
        يحوّل model → role ويستدعي Router الحقيقي.

        Returns:
            - dict إذا router sync
            - coroutine إذا router async (يُمرَّر كما هو)
        """
        role = self._map_model_to_role(model)

        if not self._warned and model:
            logger.info(
                f"🔀 RouterAdapter: model='{model}' → role='{role}'"
            )
            self._warned = True

        # نظّف kwargs
        clean_kwargs = {
            k: v for k, v in kwargs.items()
            if k in {"temperature", "max_tokens", "provider", "allow_fallback"}
        }

        # Adapt keyword arguments to legacy/test router signatures without
        # swallowing errors raised *inside* the provider implementation.
        generate = self._router.generate
        try:
            signature = inspect.signature(generate)
            parameters = signature.parameters
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            call_kwargs = {
                "system": system,
                "role": role,
                "timeout": timeout,
                **clean_kwargs,
            }
            if not accepts_kwargs:
                call_kwargs = {
                    key: value for key, value in call_kwargs.items()
                    if key in parameters
                }
        except (TypeError, ValueError):
            call_kwargs = {
                "system": system,
                "role": role,
                "timeout": timeout,
                **clean_kwargs,
            }

        result = generate(prompt, **call_kwargs)

        # Normalize async and sync responses identically so requested model and
        # provider metadata survive coroutine-based legacy routers.
        if inspect.isawaitable(result):
            async def _await_and_normalize():
                resolved = await result
                return self._normalize_result(resolved, model, role)
            return _await_and_normalize()

        return self._normalize_result(result, model, role)

    async def agenerate(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """نسخة async."""
        role = self._map_model_to_role(model)

        # إذا Router لديه agenerate
        if hasattr(self._router, "agenerate"):
            result = await self._router.agenerate(prompt, role=role, **kwargs)
        else:
            # تشغيل sync في thread
            result = self.generate(prompt, model=model, **kwargs)

        return self._normalize_result(result, model, role)

    # ═══════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════

    def _normalize_result(
        self,
        result: Any,
        model: Optional[str],
        role: str,
    ) -> Dict[str, Any]:
        """يوحّد النتيجة إلى dict."""
        # dict من router — احتفظ بحقوله
        if isinstance(result, dict):
            # تأكد من وجود الحقول المطلوبة
            if "text" not in result:
                result["text"] = result.get("raw", str(result))
            if "provider" not in result or not result.get("provider"):
                result["provider"] = "router"
            reported_model = result.get("model")
            if model and (
                not reported_model
                or str(reported_model).lower() in {"default", role.lower()}
            ):
                result["model"] = model
            elif "model" not in result:
                result["model"] = model or role
            return result

        # str — لفّها
        if isinstance(result, str):
            return {
                "text": result,
                "provider": "router",
                "model": model or role,
                "raw": result,
            }

        # أي شيء آخر
        return {
            "text": str(result),
            "provider": "router",
            "model": model or role,
            "raw": result,
        }

    def _map_model_to_role(self, model: Optional[str]) -> str:
        """يحوّل model name → role."""
        if not model:
            return "fast"

        model_lower = str(model).lower()

        if "fast" in model_lower or "small" in model_lower:
            return "fast"
        if "smart" in model_lower or "big" in model_lower:
            return "smart"
        if "reason" in model_lower:
            return "reasoning"
        if "code" in model_lower:
            return "code"

        return "fast"

    def __getattr__(self, name: str) -> Any:
        """يمرّر أي method آخر للـ Router الحقيقي."""
        return getattr(self._router, name)


def wrap_router(router) -> RouterAdapter:
    """يُلُف Router بـ Adapter."""
    return RouterAdapter(router)


__all__ = ["RouterAdapter", "wrap_router"]
