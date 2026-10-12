"""
registry_v2 — shim يتوجه إلى nova._registry.

لماذا؟ لأن المصدر الحقيقي أصبح nova._registry (nova.yaml).
هذا الملف موجود للتوافق مع الكود القديم.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from novamind.registry import (
    all_agent_names,
    agent as _agent_meta,
    agents_by_category,
    agents_by_criticality,
    core_agents as _core_agents,
    stats as _stats,
    validate as _validate,
    alias_index as _alias_index,
)


# ═══ Enums (للتوافق) ═══
class Category(str, Enum):
    CODE = "code"
    SECURITY = "security"
    QUALITY = "quality"
    INFRA = "infra"
    DATA = "data"
    UI = "ui"
    RESEARCH = "research"
    META = "meta"


class Criticality(str, Enum):
    CORE = "core"
    STANDARD = "standard"
    OPTIONAL = "optional"


# ═══ AgentSpec (للتوافق) ═══
@dataclass
class AgentSpec:
    name: str
    category: Any
    criticality: Any
    module: str
    class_name: str
    main_function: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    description: str = ""
    timeout_seconds: int = 120
    max_cost_usd: float = 0.1


def _meta_to_spec(name: str) -> AgentSpec:
    """يحوّل dict من nova._registry إلى AgentSpec."""
    m = _agent_meta(name)
    return AgentSpec(
        name=name,
        category=Category(m["category"]),
        criticality=Criticality(m["criticality"]),
        module=m["module"],
        class_name=m["class_name"],
        main_function=m.get("main_function"),
        capabilities=list(m.get("capabilities") or []),
        dependencies=list(m.get("dependencies") or []),
        description=m.get("description", ""),
        timeout_seconds=m.get("timeout_seconds", 120),
        max_cost_usd=m.get("max_cost_usd", 0.1),
    )


# ═══ UnifiedRegistry (للتوافق) ═══
class UnifiedRegistry:
    """يقرأ من nova._registry — لا تخزين داخلي."""

    @property
    def _specs(self) -> Dict[str, AgentSpec]:
        return {name: _meta_to_spec(name) for name in all_agent_names()}

    def list_all(self) -> List[str]:
        """يُرجع الأسماء الرسمية."""
        return list(all_agent_names())

    def get(self, name: str) -> Optional[AgentSpec]:
        try:
            return _meta_to_spec(name)
        except KeyError:
            return None

    def __len__(self) -> int:
        return len(all_agent_names())

    def __iter__(self):
        for name in all_agent_names():
            yield _meta_to_spec(name)


# Singleton
REGISTRY = UnifiedRegistry()

__all__ = [
    "REGISTRY",
    "UnifiedRegistry",
    "AgentSpec",
    "Category",
    "Criticality",
]
