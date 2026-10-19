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

#: سطر سياج: ` ``` ` أو `~~~` (ثلاثة أو أكثر) + وسم لغة اختياري + فراغات.
_FENCE_LINE_RE = re.compile(
    r"^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*[A-Za-z0-9_+#.\-]*[ \t]*$",
)

_NO_OUTPUT = "(لا مخرجات)"


def extract_code(text: str) -> str:
    """يستخرج الكود من ردّ الـLLM: **آخر** كتلة مُسيَّجة، وإلا النصّ كاملاً.

    «آخر» كتلة لأنّ النماذج كثيراً ما تشرح أوّلاً ثم تُنهي بالكود الصحيح.

    متسامح عن قصد — كلّ ما يلي يظهر فعلاً في ردود النماذج، وتجاهله يعني
    تمرير السياج إلى المُفسِّر فيفشل التنفيذ بخطأ نحوي ويهدر محاولة:
    مسافة بعد السياج (`` ``` python ``)، سياج بثلاثة أو أكثر من العلامات،
    سياج مائل (``~~~``)، وسياج لم يُغلق (نأخذ ما بعده).

    نصّ بلا سياج يُعاد كما هو (نماذج تُجيب كوداً عارياً).
    """
    if not text:
        return ""
    lines = text.splitlines()
    marks = [i for i, line in enumerate(lines) if _FENCE_LINE_RE.match(line)]
    if len(marks) >= 2:
        blocks = [
            "\n".join(lines[opened + 1 : closed]).strip()
            for opened, closed in zip(marks, marks[1:])
            if closed > opened + 1
        ]
        if blocks:
            return blocks[-1]
        return ""  # سياج بلا محتوى = لا كود (لا نُمرّر السياج للمُفسِّر)
    if marks:  # سياج واحد غير مُغلق ⇒ ما بعده هو المقصود (وقد لا يكون شيء)
        return "\n".join(lines[marks[-1] + 1 :]).strip()
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

    يعيد **الكود المستخرَج** لا الردّ الخام: النموذج يجيب نصّاً مُسيَّجاً
    (`` ```python … ``` ``)، وتمرير السياج إلى المُفسِّر خطأ نحوي مؤكّد ⇒
    محاولة مُهدرة في حَلقة الإصلاح. الاستخراج هنا، عند حدّ النموذج، فيبقى
    عقد المُصلِح صريحاً: «يعيد كوداً».

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
        return extract_code(str(text)) if text else ""
    return extract_code(str(raw)) if raw is not None else ""
