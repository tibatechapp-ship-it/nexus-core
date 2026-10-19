"""مُصلِح الكود — LLM عبر طبقة الوكلاء نفسها (``novamind.core.llm_router``).

برومبت التصحيح واستخراج الكود دوالّ **نقيّة** (تُختبر بلا شبكة)، والاتصال
بالشبكة محصور في ``llm_generate``. كل إخفاق يُبتلع: مزوّد واقف ⇒ نصّ فارغ ⇒
حَلقة الإصلاح تتوقّف بلا انفجار. لا استيراد لطبقة الـLLM عند الاستيراد.
"""

from __future__ import annotations

import re
from typing import Any, Optional

__all__ = ["DEFAULT_ROLE", "build_fix_prompt", "extract_code", "llm_generate"]

#: الدور المطلوب من الموجّه — «fast» أرخص وأسرع، وهو المناسب لإصلاح تركيبي.
DEFAULT_ROLE = "fast"

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+#-]*[ \t]*\r?\n(.*?)```", re.DOTALL)

_NO_OUTPUT = "(لا مخرجات)"


def extract_code(text: str) -> str:
    """يستخرج الكود من ردّ الـLLM: **آخر** كتلة مُسيَّجة، وإلا النصّ كاملاً.

    «آخر» كتلة لأنّ النماذج كثيراً ما تشرح أوّلاً ثم تُنهي بالكود الصحيح.
    """
    if not text:
        return ""
    blocks = _FENCE_RE.findall(text)
    if blocks:
        return blocks[-1].strip()
    return text.strip()


def _error_text(result: Any) -> str:
    """يجمع مخرجات الخطأ من آخر تنفيذ داخل الحكم (stderr أو سبب التحقّق)."""
    detail = getattr(result, "detail", ()) or ()
    if not detail or not isinstance(detail[-1], dict):
        return ""
    last = detail[-1]
    parts = [
        str(last.get("stderr") or ""),
        str(last.get("verify_error") or ""),
        str(last.get("stdout") or ""),
    ]
    return "\n".join(p for p in parts if p.strip())[:1500]


def build_fix_prompt(task: str, code: str, result: Any) -> str:
    """يبني رسالة الإصلاح: المهمّة + السبب + الخطأ + الكود، وبلا شرح مطلوب."""
    reason = str(getattr(result, "reason", "?") or "?")
    err = _error_text(result) or _NO_OUTPUT
    return (
        "أصلح الكود التالي حتى يُنفَّذ بنجاح (رمز الخروج 0).\n"
        f"المهمّة: {task.strip()}\n"
        f"سبب الفشل: {reason}\n"
        f"مخرجات الخطأ:\n{err}\n\n"
        "أعد الكود الكامل فقط داخل كتلة ``` بلا أي شرح.\n\n"
        f"```\n{code}\n```"
    )


def llm_generate(
    task: str,
    code: str,
    result: Any,
    system: str = "",
    *,
    router: Optional[Any] = None,
    role: str = DEFAULT_ROLE,
) -> str:
    """يطلب كوداً مُصلَحاً من الموجّه — يبتلع كل خطأ ويعيد ``""`` عند التعذّر.

    ``router`` يُمرَّر في الاختبارات (مزيّف)؛ وإلا نبنيه متأخّراً من
    ``novamind.core.llm_router`` (نفس السبيل الذي تستخدمه الوكلاء).
    """
    prompt = build_fix_prompt(task, code, result)
    try:
        if router is None:
            from novamind.core.llm_router import LLMRouter  # lazy — طبقة ثقيلة

            router = LLMRouter()
        raw = router.generate(prompt, system=system or "", role=role)
    except Exception:
        return ""
    if isinstance(raw, dict):
        text = raw.get("text")
        return str(text) if text else ""
    return str(raw) if raw is not None else ""
