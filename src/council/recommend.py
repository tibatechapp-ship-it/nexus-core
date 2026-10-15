"""استخراج التوصية النهائية من transcript المجلس.

منطق نقي (بلا I/O) — يفصل التوصية عن طبقة FastAPI في main.py حتى يصبح
قابلاً للاختبار. يعمل على أي transcript: شوط حقيقي أو نتيجة من الكاش (v1.9.2).
"""
from __future__ import annotations

import re
from collections import Counter

_REC_RE = re.compile(r"\[التوصية:\s*([^\]]+)\]")

# كلمات ليست توصيات حقيقية (أسماء الأدوار أو صياغات التوجيه)
_AGENT_WORDS = {"profiler", "analyst", "critic", "judge", "cache", "agent"}
# أحكام ثقة/تصنيفات ليست توصيات تنفيذية (تُرفض فقط في مطلع التوصية)
_VERDICT_WORDS = ("آمن", "امن", "غير آمن", "خطر", "مقبول", "مرفوض", "محايد")
_BAD_FRAGMENTS = ("اقصر", "أقصر", "خلاصة جوابك", "جوابك", "السؤال",
                  "التوجيه", "المطلوب", "المباشر", "ضع هنا", "اكتب")


def extract_recommendation(transcript) -> str:
    """تصويت بالأغلبية على سطور ``[التوصية: ...]`` داخل الـ transcript.

    يُرجع التوصية الأكثر تكراراً، أو ``""`` إن لم توجد توصية صالحة.
    """
    try:
        recs = []
        for entry in (transcript or []):
            txt = entry.get("response", "") if isinstance(entry, dict) else str(entry)
            match = _REC_RE.search(txt or "")
            if not match:
                continue
            rec = match.group(1).strip().strip(".").strip("<>").strip()
            if rec and rec.lower() not in _AGENT_WORDS and len(rec) >= 2 \
                    and not rec.startswith(_VERDICT_WORDS) \
                    and not any(bad in rec for bad in _BAD_FRAGMENTS):
                recs.append(rec)
        if recs:
            return Counter(recs).most_common(1)[0][0]
    except Exception:
        pass
    return ""


__all__ = ["extract_recommendation"]
