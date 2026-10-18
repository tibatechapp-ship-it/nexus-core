"""Self-reflection for chat answers — rate, retry once, spot awareness gaps.

Phase 1's judgement layer: *pure* functions only (prompt builders, a tolerant
parser, the retry decision and the awareness-gap rule).  The gateway owns the
actual LLM call and feeds the text back through :func:`parse_reflection`, so
everything here is deterministic and fully offline-testable.

Honest scope of :func:`awareness_gap` (phase 1): the only *objective* signal
available without user feedback is the technical outcome (``signal_ok``), so
the gap is "claims a good answer although the run failed" — user-verified
ground truth comes in a later phase.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

__all__ = [
    "RATINGS",
    "REFLECTION_SYSTEM",
    "RETRY_GRACE",
    "awareness_gap",
    "build_reflection_prompt",
    "build_retry_system",
    "memory_block",
    "parse_reflection",
    "rating_score",
    "should_retry",
]

#: The three self-rating classes (best → worst).
RATINGS: tuple[str, ...] = ("excellent", "good", "poor")

#: Scores fed into the genome's task channel (``quality``).
_SCORES: dict[str, float] = {"excellent": 1.0, "good": 0.75, "poor": 0.4}

#: System prompt for the reflection call — JSON only, nothing else.
REFLECTION_SYSTEM = (
    "أنت مُقيّم ذاتي دقيق. قيّم الإجابة على أسسها فقط، وأعد JSON حصراً "
    'بلا أي نصّ آخر: {"rating": "excellent|good|poor", "reason": "..."} '
    "باختصار بالعربية."
)

#: Suffix appended to the agent system prompt when re-answering a poor reply.
RETRY_GRACE = (
    "\n\nتنبيه المُقيّم الذاتي: الإجابة السابقة قُيّمت ركيكة — أعد الصياغة "
    "من جديد بتقديم أوضح وأدق، ولا تكرّر محتواها."
)

_JSON_RE = re.compile(r"\{[^{}]*\}", re.S)

#: Keyword fallbacks, scanned in priority order (negations are best-effort:
#: the JSON path is the primary contract and the model is told "JSON only").
_EXCELLENT_MARKS = ("ممتاز", "excellent", "exceptional", "perfect")
_POOR_MARKS = (
    "رديء", "ردئ", "ضعيف", "سيئ", "سيء", "ركيك", "غير جيد",
    "weak", "poor", "bad", "terrible",
)
_GOOD_MARKS = ("جيد", "good", "acceptable", "مقبول", "مقبولة")


def build_reflection_prompt(question: str, answer: str) -> str:
    """The user turn handed to the reflection call."""
    return (
        f"السؤال:\n{(question or '').strip()[:2000]}\n\n"
        f"الإجابة:\n{(answer or '').strip()[:4000]}\n\n"
        "قيّم الإجابة وأعد JSON فقط."
    )


def build_retry_system(system: str, reason: str | None) -> str:
    """Agent system prompt + the critic's note, for the single retry."""
    note = RETRY_GRACE
    if reason:
        note = (
            "\n\nتنبيه المُقيّم الذاتي: الإجابة السابقة قُيّمت ركيكة "
            f"({reason.strip()[:300]}) — أعد الصياغة من جديد بتقديم أوضح "
            "وأدق، ولا تكرّر محتواها."
        )
    return f"{system}{note}"


def _find_rating(text: str) -> str | None:
    """First rating class whose keyword appears in ``text`` (priority order)."""
    low = (text or "").lower()
    if not low.strip():
        return None
    for marks, rating in (
        (_EXCELLENT_MARKS, "excellent"),
        (_POOR_MARKS, "poor"),
        (_GOOD_MARKS, "good"),
    ):
        if any(mark in low for mark in marks):
            return rating
    return None


def parse_reflection(text: str) -> tuple[str | None, str | None]:
    """``(rating, reason)`` from a reflection reply — tolerant, never raises.

    Tries the JSON contract first (``{"rating": ..., "reason": ...}``), then
    falls back to a keyword scan of the raw text.  Unparseable → ``(None, None)``
    (the gateway treats that as "no rating": no retry, nothing scored).
    """
    if not (text or "").strip():
        return None, None
    match = _JSON_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(0))
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            rating = _find_rating(str(data.get("rating") or ""))
            if rating:
                reason = str(data.get("reason") or "").strip()[:500] or None
                return rating, reason
    return _find_rating(text), None


def rating_score(rating: str | None) -> float | None:
    """Genome ``quality`` for a rating (``None``/unknown → ``None``)."""
    if not rating:
        return None
    return _SCORES.get(rating)


def should_retry(rating: str | None) -> bool:
    """Retry exactly once, and only for an explicitly poor rating."""
    return rating == "poor"


def awareness_gap(
    rating: str | None,
    signal_ok: bool,
    retry_rating: str | None = None,
) -> int | None:
    """Did the agent *know* how it did?  ``1`` = gap, ``0`` = aligned, ``None``
    = not judgeable from technical signals alone.

    * failed run but the agent claims good/excellent → **gap**;
    * failed run and it says poor → it knew (aligned);
    * successful run rated poor whose retry then scored good/excellent → it
      knew the first answer was weak (aligned);
    * anything else (no rating, or a normal success) → ``None``.
    """
    if rating is None:
        return None
    if not signal_ok:
        return 1 if rating in ("excellent", "good") else 0
    if rating == "poor" and retry_rating in ("good", "excellent"):
        return 0
    return None


def _clip(text: str, limit: int = 400) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def memory_block(
    rows: Sequence[dict[str, Any]], limit: int = 3
) -> str:
    """Prompt block over past interactions — ``""`` when there is nothing."""
    picked = list(rows)[: max(0, int(limit))]
    if not picked:
        return ""
    lines = ["### ذاكرة الميدان (تفاعلات سابقة مشابهة)"]
    for row in picked:
        question = _clip(str(row.get("question") or ""), 200)
        answer = _clip(str(row.get("answer") or ""), 400)
        rating = str(row.get("self_rating") or "بدون تقييم")
        who = str(row.get("agent_id") or "-")
        lines.append(f"- [{who}] س: {question} — ج ({rating}): {answer}")
    return "\n".join(lines)
