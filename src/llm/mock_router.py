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
        return {"ok": True, "text": t, "provider": "mock", "elapsed": 0.01}

    LLMRouter.generate = mock_gen  # type: ignore[method-assign]
    LLMRouter.generate_for_task = (  # type: ignore[method-assign]
        lambda self, *a, **kw: mock_gen(self, *a, **kw))
    LLMRouter._load_from_env = (  # type: ignore[method-assign]
        lambda self: setattr(self, "providers", []))
    LLMRouter._cooldown_provider = (  # type: ignore[method-assign]
        lambda self, n, seconds=300: None)
    LLMRouter._is_cooled_down = lambda self, n: True  # type: ignore[method-assign]
