"""نظام الهوية العسكرية"""
from .military_id import (
    MilitaryID, Rank, Clearance, Branch,
    RankHierarchy, IDGenerator, Fingerprint,
    AgentProfile, PersonnelRegistry,
)
from .hallucination_guard import (
    HallucinationGuard, HallucinationDetector,
    HallucinationType, Severity, HallucinationEvent,
)
from .promotion_system import (
    PromotionSystem, PerformanceMetrics, PromotionVerdict,
)
__all__ = [
    "MilitaryID", "Rank", "Clearance", "Branch",
    "RankHierarchy", "IDGenerator", "Fingerprint",
    "AgentProfile", "PersonnelRegistry",
    "HallucinationGuard", "HallucinationDetector",
    "HallucinationType", "Severity", "HallucinationEvent",
    "PromotionSystem", "PerformanceMetrics", "PromotionVerdict",
]
