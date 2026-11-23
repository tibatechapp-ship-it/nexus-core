"""المزوّد الوهمي الحتمي — بيئة مغلقة بلا مفاتيح وبلا إنترنت.

كان يعيش في اللوحة القديمة (``src/web/app.py``)؛ منذ حذف اللوحة
(v1.61.0) صار ملكاً مشتركاً معلناً لأي مثال أو فحص يعمل بلا مزوّد:
نُبطّن ``LLMRouter`` بمولّد mock حتمي — نفس المدخل يعطي نفس المخرج،
وبلا شبكة إطلاقاً.
"""

from __future__ import annotations

from typing import Any

__all__ = ["setup_mock"]


def setup_mock() -> None:
    """بطّن الموجّه بمولّد mock حتمي — يُستدعى قبل بناء المحرك."""
    from novamind.core.llm_router import LLMRouter

    def mock_gen(self: Any, prompt: str = "", system: str = "",
                 **kw: Any) -> dict[str, Any]:
        s = str(system)
        p = str(prompt)
        is_debate = "راجع" in p
        if "أنت الناقد" in s:
            t = "بعد المراجعة: متسقتان. مقبول." if is_debate else "أراجع الحجتين. مقبول."
        elif "أنت المحلل المتشكك" in s:
            t = "خطر: نقص السياق الأمني." if is_debate else "خطر: 3 مخاوف أمنية."
        elif "أنت المحلل المدافع" in s:
            t = "آمن: يمكن التخفيف." if is_debate else "آمن: الطلب مقبول."
        else:
            t = f"[Mock] {p[:80]}"
        return {
            "ok": True,
            "text": t,
            "provider": "mock",
            "model": "mock",
            "elapsed": 0.01,
            "simulated": True,
        }

    LLMRouter.generate = mock_gen  # type: ignore[method-assign]

    def mock_task(
        self: Any,
        task_type: str = "",
        prompt: str = "",
        system: str = "",
        **kw: Any,
    ) -> dict[str, Any]:
        # Preserve the canonical generate_for_task signature; do not
        # accidentally treat the task label as prompt text.
        return mock_gen(
            self, prompt=prompt, system=system, task_type=task_type, **kw
        )

    LLMRouter.generate_for_task = mock_task  # type: ignore[method-assign]
    LLMRouter._load_from_env = (  # type: ignore[method-assign]
        lambda self: setattr(self, "providers", []))
    LLMRouter._cooldown_provider = (  # type: ignore[method-assign]
        lambda self, n, seconds=300: None)
    LLMRouter._is_cooled_down = lambda self, n: True  # type: ignore[method-assign]
