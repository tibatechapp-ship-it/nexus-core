"""Shared contracts for NEXUS CORE intelligence and assurance engines."""

from .contracts import (
    CONTRACT_VERSION,
    MAX_EVIDENCE,
    MAX_FINDINGS,
    ContractError,
    EvidenceReference,
    Finding,
    FindingStatus,
    IntelligenceResult,
    ResultStatus,
    Severity,
)

__all__ = [
    "CONTRACT_VERSION",
    "MAX_EVIDENCE",
    "MAX_FINDINGS",
    "ContractError",
    "EvidenceReference",
    "Finding",
    "FindingStatus",
    "IntelligenceResult",
    "ResultStatus",
    "Severity",
]
