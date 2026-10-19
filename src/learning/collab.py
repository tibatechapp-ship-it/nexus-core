"""Phase 2 Day 3 — multi-agent collaboration primitives.

Three composable, hermetically-testable helpers on top of the tool layer:

* :func:`classify_question` — bucket a question into exactly one of
  ``technical`` / ``analytical`` / ``strategic`` / ``critical`` /
  ``organizational`` (injectable classifier; an LLM-backed default that
  degrades to a pure keyword classifier when the LLM layer is unavailable).
* :func:`consult` — a primary agent answers, a secondary agent critiques, and
  if the critique flags ``خطأ``/``ضعف`` the primary revises with the notes
  (bounded by ``max_retries`` — never an infinite loop).
* :func:`multi_agent_consensus` — every agent answers independently and a
  synthesizer merges the answers into one consensus; a failing agent is
  skipped, never fatal.

Design notes (same contract as :mod:`src.learning.tools` and
:mod:`src.learning.react_agent`):

* Everything network-shaped is injectable (``classifier`` / ``ask_fn`` /
  ``synthesize_fn``) so the whole module is testable at 100% coverage with
  fake LLMs — no network, no keys.
* The LLM default is imported LAZILY (the optional ``novamind`` layer) and
  any failure falls back to the pure keyword classifier — classification
  never crashes the caller.
* :func:`consult` re-critiques after every revision, so ``max_retries > 1``
  is meaningful; the loop is strictly bounded either way.
"""

from __future__ import annotations

import re
from typing import Any, Callable

__all__ = [
    "CATEGORIES",
    "AskFn",
    "ClassifierFn",
    "SynthesizeFn",
    "classify_question",
    "consult",
    "multi_agent_consensus",
]

# The five question families (fixed order — it is also the tie-break order).
CATEGORIES: tuple[str, ...] = (
    "technical",
    "analytical",
    "strategic",
    "critical",
    "organizational",
)

# Injected-LLM contracts.
ClassifierFn = Callable[[str], str]
AskFn = Callable[[str, str], str]
SynthesizeFn = Callable[[str, list[str]], str]

# A critique that contains any of these markers triggers one more revision.
_RETRY_MARKERS: tuple[str, ...] = ("خطأ", "ضعف")

# Category aliases an LLM may answer with (English slug + Arabic label).
_SLUG_ALIASES: dict[str, tuple[str, ...]] = {
    "technical": ("technical", "تقني"),
    "analytical": ("analytical", "تحليلي"),
    "strategic": ("strategic", "استراتيجي"),
    "critical": ("critical", "نقدي"),
    "organizational": ("organizational", "تنظيمي"),
}

# Keyword stems (Arabic + English), matched as substrings AFTER normalisation.
# Prefer prefix-stable stems: an inflected word still contains the stem
# (استراتيجيتنا ⊃ استراتيج) while a full word often does not (رؤية ⊄ رؤيتنا).
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "technical": (
        "كود", "برمج", "دالة", "خطا", "خلل", "بايثون", "خادم", "قاعدة بيانات",
        "api", "code", "function", "bug", "python", "sql", "install",
        "server", "error", "debug",
    ),
    "analytical": (
        "حلل", "تحليل", "بيانات", "مقارن", "ارقام", "احصاء", "تقرير", "اتجاه",
        "analyze", "data", "compare", "trend", "metric", "report", "statistics",
    ),
    "strategic": (
        "استراتيج", "توسع", "مستقبل", "نمو", "سوق", "رؤية",
        "strategy", "vision", "growth", "expansion", "market", "roadmap",
    ),
    "critical": (
        "نقد", "تقييم", "مراجعة", "ضعف", "مخاطر",
        "critique", "review", "weakness", "risk", "evaluate", "flaw",
    ),
    "organizational": (
        "نظم", "تنظيم", "جدول", "مهام", "فريق", "توصيه", "اولويه",
        "organization", "schedule", "team", "task", "workflow", "priority",
    ),
}

# When nothing matches at all, the neutral middle category wins.
_FALLBACK_CATEGORY = "analytical"

_CLASSIFY_SYSTEM = (
    "أنت مصنّف أسئلة. صنّف السؤال إلى فئة واحدة فقط من: "
    "technical, analytical, strategic, critical, organizational. "
    "أجب باسم الفئة بالإنجليزية فقط، بلا شرح."
)

_DIACRITICS_RE = re.compile(r"[ً-ْٰـ]")
_ARABIC_TRANSLATION = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})


def _norm(text: str) -> str:
    """Arabic-aware normalisation (lower FIRST, then strip, then map)."""
    lowered = str(text).lower()
    stripped = _DIACRITICS_RE.sub("", lowered)
    return stripped.translate(_ARABIC_TRANSLATION)


def _keyword_classify(text: str) -> str:
    """Pure fallback: pick the category with the most keyword hits."""
    normed = _norm(text)
    best = _FALLBACK_CATEGORY
    best_hits = 0
    for category in CATEGORIES:
        hits = sum(1 for kw in _CATEGORY_KEYWORDS[category] if _norm(kw) in normed)
        if hits > best_hits:  # strict > keeps the fixed order as tie-break
            best, best_hits = category, hits
    return best


def _extract_category(text: str) -> str:
    """Pull a category out of an LLM reply; keyword-classify when absent."""
    normed = _norm(text)
    for category in CATEGORIES:
        for alias in _SLUG_ALIASES[category]:
            if _norm(alias) in normed:
                return category
    return _keyword_classify(text)


def _llm_classify(question: str) -> str:
    """Ask the (optional) novamind LLM router — lazy import, never at module load."""
    from novamind.core.llm_router import LLMRouter  # lazy — optional layer

    router = LLMRouter()
    return str(router.generate(question, system=_CLASSIFY_SYSTEM, role="fast"))


def _default_classifier(question: str) -> str:
    """LLM classification with a pure keyword fallback — never raises."""
    try:
        return _extract_category(_llm_classify(question))
    except Exception:  # the LLM layer is optional; degrade, never crash
        return _keyword_classify(question)


def classify_question(question: str, *, classifier: ClassifierFn | None = None) -> str:
    """Return exactly one of :data:`CATEGORIES` for ``question``.

    ``classifier`` is injectable (tests pass a fake); the default routes
    through :func:`_default_classifier` (LLM, keyword fallback).
    """
    fn: ClassifierFn = classifier if classifier is not None else _default_classifier
    return _extract_category(str(fn(question)))


def _critique_prompt(question: str, answer: str) -> str:
    return (
        "أنت وكيل نقدي. أجب بنقد قصير ومباشر للإجابة التالية.\n"
        f"السؤال: {question}\nالإجابة: {answer}\n"
        "اذكر بوضوح إن وُجد «خطأ» أو «ضعف»، وإلا قل: الإجابة مقبولة."
    )


def _revise_prompt(question: str, answer: str, critique: str) -> str:
    return (
        f"أعد كتابة إجابة أفضل للسؤال: {question}\n"
        f"إجابتك السابقة: {answer}\nملاحظات الناقد: {critique}"
    )


def _needs_revision(critique: str) -> bool:
    return any(marker in critique for marker in _RETRY_MARKERS)


def consult(
    primary_agent: str,
    secondary_agent: str,
    question: str,
    *,
    ask_fn: AskFn,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Primary answers → secondary critiques → revise while flagged.

    Returns ``{"answer", "critique", "retries", "final_answer"}`` where
    ``critique`` is the LAST critique received and ``retries`` counts how
    many revisions actually happened (bounded by ``max_retries``).
    """
    answer = str(ask_fn(primary_agent, question))
    critique = str(ask_fn(secondary_agent, _critique_prompt(question, answer)))
    retries = 0
    while retries < max_retries and _needs_revision(critique):
        answer = str(ask_fn(primary_agent, _revise_prompt(question, answer, critique)))
        retries += 1
        critique = str(ask_fn(secondary_agent, _critique_prompt(question, answer)))
    return {
        "answer": answer,
        "critique": critique,
        "retries": retries,
        "final_answer": answer,
    }


def multi_agent_consensus(
    question: str,
    agents: list[str],
    *,
    ask_fn: AskFn,
    synthesize_fn: SynthesizeFn,
) -> dict[str, Any]:
    """Every agent answers; a synthesizer merges them into one consensus.

    A failing agent is skipped (never fatal).  Returns ``{"consensus",
    "individual_answers", "agents_used"}`` where ``individual_answers`` is a
    list of ``{"agent", "answer"}`` dicts in call order.
    """
    individual: list[dict[str, str]] = []
    used: list[str] = []
    for agent in agents:
        try:
            reply = str(ask_fn(agent, question))
        except Exception:  # one dead agent must not kill the round
            continue
        individual.append({"agent": str(agent), "answer": reply})
        used.append(str(agent))
    answers = [item["answer"] for item in individual]
    if not answers:
        return {"consensus": "", "individual_answers": [], "agents_used": []}
    try:
        consensus = str(synthesize_fn(question, answers))
    except Exception:  # synthesis failure degrades to a plain join
        consensus = "\n".join(answers)
    return {
        "consensus": consensus,
        "individual_answers": individual,
        "agents_used": used,
    }
