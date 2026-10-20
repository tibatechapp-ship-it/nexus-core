"""Risk classification — deterministic, no LLM."""
from __future__ import annotations
from enum import StrEnum
from typing import Tuple


class RiskLevel(StrEnum):
    """Risk level as a string enum.

    ``StrEnum`` (Python 3.11+) makes ``str(RiskLevel.HIGH) == "high"`` — without
    it a ``(str, Enum)`` leaks ``"RiskLevel.HIGH"`` through ``str()``/f-strings.
    """

    LOW = "low"
    MED = "med"
    HIGH = "high"


# Explicit ordering — ``max()`` must never rely on the enum's own comparison.
RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MED: 1, RiskLevel.HIGH: 2}


def risk_key(level: RiskLevel) -> int:
    """Sort key for ``RiskLevel`` — use with ``sorted``/``max``/``min``.

    A plain ``max(levels)`` is unsafe: ``max()`` compares with ``>`` and an enum
    that only defines ``__lt__`` falls back to str comparison, mispicking the
    highest risk (``max([HIGH, MED])`` returned ``MED``).
    """
    return RISK_ORDER[level]


_HIGH_PATTERNS = (
    "genome", "genome_v2", "genome_store",
    "auth", "secret", "password",
    "delete", "drop", "truncate",
    "production", "prod", "deploy",
    "migration", "schema",
    "nexus_agent.py", "conftest.py",
)
# Words too common to mean "dangerous" on their own — HIGH only when paired
# with a destructive verb nearby (e.g. "delete ... token", "rotate token").
_HIGH_CONTEXTUAL = (
    ("token", ("delete", "drop", "truncate", "rotate", "purge",
               "remove", "revoke", "leak", "secret", "auth")),
)
_LOW_PATTERNS = (
    "add test", "write test", "add comment",
    "add docstring", "read ", "show ", "list ",
    "explain", "describe", "what is", "how does",
)


def _contextual_high(text: str) -> Tuple[str, ...]:
    """High-risk words that only fire when a destructive/security verb is near."""
    hits = []
    for word, triggers in _HIGH_CONTEXTUAL:
        if word in text and any(t in text for t in triggers):
            hits.append(word)
    return tuple(hits)


def classify(request: str) -> RiskLevel:
    if not isinstance(request, str) or not request.strip():
        return RiskLevel.MED
    text = request.lower()
    if any(p in text for p in _HIGH_PATTERNS):
        return RiskLevel.HIGH
    if _contextual_high(text):
        return RiskLevel.HIGH
    if any(p in text for p in _LOW_PATTERNS):
        return RiskLevel.LOW
    return RiskLevel.MED


def explain(request: str) -> dict:
    text = (request or "").lower()
    matched_high = [p for p in _HIGH_PATTERNS if p in text]
    matched_high.extend(_contextual_high(text))
    matched_low = [p for p in _LOW_PATTERNS if p in text]
    level = classify(request)
    if matched_high:
        reason = "high:" + matched_high[0]
    elif matched_low:
        reason = "low:" + matched_low[0]
    else:
        reason = "default:med"
    return {"level": level.value, "matched_high": matched_high,
            "matched_low": matched_low, "reason": reason}
