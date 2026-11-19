"""Deterministic, fail-closed assurance evaluation for intelligence results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Iterable

from .contracts import EvidenceReference, FindingStatus, IntelligenceResult, ResultStatus


class AssuranceVerdict(StrEnum):
    ASSURED = "assured"
    NEEDS_HUMAN = "needs_human"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AssuranceDecision:
    """Auditable decision; this does not authorize execution or deployment."""

    verdict: AssuranceVerdict
    reasons: tuple[str, ...]
    verified_evidence_ids: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.verdict is AssuranceVerdict.ASSURED

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "verified_evidence_ids": list(self.verified_evidence_ids),
        }


EvidenceVerifier = Callable[[EvidenceReference], bool]


def evaluate_assurance(
    result: IntelligenceResult,
    *,
    authorized_scope: Iterable[str],
    verify_evidence: EvidenceVerifier,
) -> AssuranceDecision:
    """Evaluate provenance and scope without running target code.

    The verifier must independently retrieve/check each evidence reference.
    Only the literal boolean True counts as verified. This gate deliberately
    does not interpret a clean scan as proof of absence of defects.
    """
    if not isinstance(result, IntelligenceResult):
        return AssuranceDecision(
            AssuranceVerdict.REJECTED, ("invalid intelligence result",), ()
        )
    if not callable(verify_evidence):
        return AssuranceDecision(
            AssuranceVerdict.REJECTED, ("evidence verifier is required",), ()
        )

    try:
        allowed = frozenset(authorized_scope)
    except (TypeError, ValueError):
        allowed = frozenset()
    if not allowed or not set(result.scope).issubset(allowed):
        return AssuranceDecision(
            AssuranceVerdict.REJECTED, ("result scope exceeds or lacks authorization",), ()
        )

    if result.status in (ResultStatus.REJECTED, ResultStatus.FAILED):
        return AssuranceDecision(
            AssuranceVerdict.REJECTED, (f"engine status is {result.status.value}",), ()
        )
    if not result.evidence:
        return AssuranceDecision(
            AssuranceVerdict.REJECTED, ("result contains no verifiable evidence",), ()
        )

    verified: list[str] = []
    failures: list[str] = []
    for evidence in result.evidence:
        try:
            valid = verify_evidence(evidence)
        except Exception:
            valid = False
        if valid is True:
            verified.append(evidence.evidence_id)
        else:
            failures.append(evidence.evidence_id)

    if failures:
        return AssuranceDecision(
            AssuranceVerdict.REJECTED,
            ("evidence verification failed: " + ", ".join(failures),),
            tuple(verified),
        )

    reasons: list[str] = []
    if result.status is ResultStatus.PARTIAL:
        reasons.append("engine result is partial")
    unresolved = [
        finding.finding_id
        for finding in result.findings
        if finding.status in (FindingStatus.CANDIDATE, FindingStatus.INCONCLUSIVE)
    ]
    if unresolved:
        reasons.append("findings require independent review: " + ", ".join(unresolved))

    if reasons:
        return AssuranceDecision(
            AssuranceVerdict.NEEDS_HUMAN, tuple(reasons), tuple(verified)
        )
    return AssuranceDecision(
        AssuranceVerdict.ASSURED, ("all evidence references verified",), tuple(verified)
    )


__all__ = [
    "AssuranceDecision", "AssuranceVerdict", "EvidenceVerifier", "evaluate_assurance",
]
