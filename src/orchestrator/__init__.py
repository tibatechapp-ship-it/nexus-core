"""Orchestrator — risk + routing + decomposition + jury gate."""
from .risk import RiskLevel, classify, explain
from .router import route, route_with_reason
from .registry import AgentRegistry, get_registry, RegistryError
from .decomposer import SubTask, decompose, merge_outputs, split_clauses
from .orchestrator import Orchestrator, Plan, decompose_enabled

__all__ = [
    "RiskLevel", "classify", "explain",
    "route", "route_with_reason",
    "AgentRegistry", "get_registry", "RegistryError",
    "SubTask", "decompose", "merge_outputs", "split_clauses",
    "Orchestrator", "Plan", "decompose_enabled",
]
