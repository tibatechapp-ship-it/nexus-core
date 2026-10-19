"""Risk classification — deterministic, no LLM."""
from __future__ import annotations
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MED = "med"
    HIGH = "high"

    def __lt__(self, other: "RiskLevel") -> bool:  # type: ignore[override]
        order = {"low": 0, "med": 1, "high": 2}
        return order[self.value] < order[other.value]


_HIGH_PATTERNS = (
    "genome", "genome_v2", "genome_store",
    "auth", "token", "secret", "password",
    "delete", "drop", "truncate",
    "production", "prod", "deploy",
    "migration", "schema",
    "nexus_agent.py", "conftest.py",
)
_LOW_PATTERNS = (
    "add test", "write test", "add comment",
    "add docstring", "read ", "show ", "list ",
    "explain", "describe", "what is", "how does",
)


def classify(request: str) -> RiskLevel:
    if not isinstance(request, str) or not request.strip():
        return RiskLevel.MED
    text = request.lower()
    if any(p in text for p in _HIGH_PATTERNS):
        return RiskLevel.HIGH
    if any(p in text for p in _LOW_PATTERNS):
        return RiskLevel.LOW
    return RiskLevel.MED


def explain(request: str) -> dict:
    text = (request or "").lower()
    matched_high = [p for p in _HIGH_PATTERNS if p in text]
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
