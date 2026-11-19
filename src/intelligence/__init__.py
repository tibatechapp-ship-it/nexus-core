"""Shared intelligence contracts, assurance, and behavior primitives."""

from .contracts import (
    CONTRACT_VERSION, MAX_EVIDENCE, MAX_FINDINGS, ContractError,
    EvidenceReference, Finding, FindingStatus, IntelligenceResult,
    ResultStatus, Severity,
)
from .gate import (
    AssuranceDecision, AssuranceVerdict, EvidenceVerifier, evaluate_assurance,
)
from .behavior import (
    BehaviorBaseline, BehaviorCase, BehaviorComparison, BehaviorContractError,
    BehaviorObservation, BehaviorVerdict, ObservationStatus, compare_behavior,
    digest_payload,
)

__all__ = [
    "CONTRACT_VERSION", "MAX_EVIDENCE", "MAX_FINDINGS", "ContractError",
    "EvidenceReference", "Finding", "FindingStatus", "IntelligenceResult",
    "ResultStatus", "Severity", "AssuranceDecision", "AssuranceVerdict",
    "EvidenceVerifier", "evaluate_assurance", "BehaviorBaseline", "BehaviorCase",
    "BehaviorComparison", "BehaviorContractError", "BehaviorObservation",
    "BehaviorVerdict", "ObservationStatus", "compare_behavior", "digest_payload",
]
