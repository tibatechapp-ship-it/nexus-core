"""Shared intelligence contracts and assurance primitives."""

from .contracts import (
    CONTRACT_VERSION, MAX_EVIDENCE, MAX_FINDINGS, ContractError,
    EvidenceReference, Finding, FindingStatus, IntelligenceResult,
    ResultStatus, Severity,
)
from .gate import (
    AssuranceDecision, AssuranceVerdict, EvidenceVerifier, evaluate_assurance,
)

__all__ = [
    "CONTRACT_VERSION", "MAX_EVIDENCE", "MAX_FINDINGS", "ContractError",
    "EvidenceReference", "Finding", "FindingStatus", "IntelligenceResult",
    "ResultStatus", "Severity", "AssuranceDecision", "AssuranceVerdict",
    "EvidenceVerifier", "evaluate_assurance",
]
