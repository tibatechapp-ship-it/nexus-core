"""Shared intelligence contracts, assurance, and behavior primitives."""

from .contracts import (
    CONTRACT_VERSION, MAX_EVIDENCE, MAX_FINDINGS, ContractError,
    EvidenceReference, Finding, FindingStatus, IntelligenceResult,
    ResultStatus, Severity,
)
from .gate import (
    AssuranceDecision, AssuranceVerdict, EvidenceVerifier, evaluate_assurance,
)
from .capture import CaptureError, CapturedCase, EvidenceSink, capture_baseline, capture_observations
from .replay import BehaviorReplayError, ReplayCommandCase, execute_authorized_cases
from .mission import (
    BehaviorCaseSpec, MissionBehaviorError, MissionBehaviorReplayResult,
    run_mission_behavior_replay,
)
from .behavior import (
    BehaviorBaseline, BehaviorCase, BehaviorComparison, BehaviorContractError,
    BehaviorGateDecision, BehaviorGateVerdict, BehaviorObservation, BehaviorVerdict,
    ObservationStatus, compare_behavior, digest_payload, evaluate_behavior_gate,
)

__all__ = [
    "CONTRACT_VERSION", "MAX_EVIDENCE", "MAX_FINDINGS", "ContractError",
    "EvidenceReference", "Finding", "FindingStatus", "IntelligenceResult",
    "ResultStatus", "Severity", "AssuranceDecision", "AssuranceVerdict",
    "EvidenceVerifier", "evaluate_assurance", "BehaviorBaseline", "BehaviorCase",
    "BehaviorComparison", "BehaviorContractError", "BehaviorGateDecision",
    "BehaviorGateVerdict", "BehaviorObservation", "BehaviorVerdict", "ObservationStatus",
    "compare_behavior", "digest_payload", "evaluate_behavior_gate",
    "CaptureError", "CapturedCase", "EvidenceSink", "capture_baseline",
    "capture_observations", "BehaviorReplayError", "ReplayCommandCase",
    "execute_authorized_cases", "BehaviorCaseSpec", "MissionBehaviorError",
    "MissionBehaviorReplayResult", "run_mission_behavior_replay",
]
