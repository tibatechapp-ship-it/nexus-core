"""NovaMind Registry — الواجهة الموحدة.

- v2: السجل الموحد (79 وكيل، 8 فئات، 21 core) — للاستعلام
- core: المصدر الحقيقي (nova.yaml) — للإحصائيات والتحقق
"""
from __future__ import annotations

from typing import Any, Optional

# ═══ v2 — للاستعلام عن الوكلاء ═══
from novamind.registry.v2 import (
    UnifiedRegistry,
    Category,
    Criticality,
    AgentSpec,
    REGISTRY,
)

# ═══ core — للإحصائيات والتحقق (nova.yaml) ═══
try:
    from novamind.registry.core import (
        stats as _core_stats,
        validate as _core_validate,
        get_agent as _core_get_agent,
        list_agents as _core_list_agents,
        load_registry as _core_load_registry,
        has_permission as _core_has_permission,
        can_use_tool as _core_can_use_tool,
        all_pipeline_ids as _core_all_pipeline_ids,
        all_pipelines as _core_all_pipelines,
        pipeline as _core_pipeline,
    )
    _CORE_AVAILABLE = True
except ImportError:
    _CORE_AVAILABLE = False
    _core_stats = None
    _core_validate = None
    _core_get_agent = None
    _core_list_agents = None
    _core_load_registry = None
    _core_has_permission = None
    _core_can_use_tool = None
    _core_all_pipeline_ids = None
    _core_all_pipelines = None
    _core_pipeline = None


# ═══════════════════════════════════════════════════════════════
# Wrapper Functions
# ═══════════════════════════════════════════════════════════════

def stats() -> dict:
    """إحصائيات الوكلاء."""
    if _CORE_AVAILABLE and _core_stats:
        try:
            return _core_stats()
        except Exception:
            pass
    s = REGISTRY.stats()
    return {
        "agents_total": s.get("total", len(REGISTRY)),
        "categories": [c.value for c in Category],
        "criticalities": [c.value for c in Criticality],
    }


def validate() -> list:
    """فحص السجل."""
    if _CORE_AVAILABLE and _core_validate:
        try:
            return _core_validate()
        except Exception as e:
            return [f"core.validate() failed: {e}"]
    return []


def all_agent_names() -> list:
    """كل أسماء الوكلاء (79)."""
    if _CORE_AVAILABLE and _core_list_agents:
        try:
            return _core_list_agents()
        except Exception:
            pass
    return [spec.name for spec in REGISTRY.list_all()]


def get_agent(name: str) -> dict:
    """تفاصيل وكيل واحد."""
    if _CORE_AVAILABLE and _core_get_agent:
        try:
            return _core_get_agent(name)
        except KeyError:
            raise
        except Exception:
            pass
    spec = REGISTRY.get(name)
    if spec and hasattr(spec, "to_dict"):
        return spec.to_dict()
    raise KeyError(f"Agent '{name}' not found")


# ═══════════════════════════════════════════════════════════════
# Backward compatibility (للوكلاء الذين يستوردون load_registry, agent)
# ═══════════════════════════════════════════════════════════════

def load_registry() -> dict:
    """تحميل السجل الكامل (توافق مع core)."""
    if _CORE_AVAILABLE and _core_load_registry:
        return _core_load_registry()
    raise RuntimeError("core.load_registry غير متاح")


def agent(name: str) -> dict:
    """تفاصيل وكيل (توافق مع core)."""
    return get_agent(name)


def list_agents() -> list:
    """توافق مع core.list_agents."""
    return all_agent_names()


def has_permission(agent_name: str, permission: str) -> bool:
    """فحص RBAC."""
    if _CORE_AVAILABLE and _core_has_permission:
        return _core_has_permission(agent_name, permission)
    return True


def can_use_tool(agent_name: str, tool: str) -> bool:
    """فحص استخدام أداة."""
    if _CORE_AVAILABLE and _core_can_use_tool:
        return _core_can_use_tool(agent_name, tool)
    return True


def all_pipeline_ids() -> list:
    """أسماء Pipelines."""
    if _CORE_AVAILABLE and _core_all_pipeline_ids:
        return _core_all_pipeline_ids()
    return []


def all_pipelines() -> dict:
    """كل Pipelines."""
    if _CORE_AVAILABLE and _core_all_pipelines:
        return _core_all_pipelines()
    return {}


def pipeline(pipeline_id: str) -> Optional[dict]:
    """تفاصيل pipeline."""
    if _CORE_AVAILABLE and _core_pipeline:
        return _core_pipeline(pipeline_id)
    return None


# ═══════════════════════════════════════════════════════════════
# Exports
# ═══════════════════════════════════════════════════════════════



def alias_index() -> dict:
    """خريطة alias → canonical (من nova.yaml)."""
    if _CORE_AVAILABLE and _core_load_registry:
        try:
            data = _core_load_registry()
            return data.get("alias_index", {})
        except Exception:
            pass
    # Fallback: من v2
    return {}


__all__ = [
    # v2
    "UnifiedRegistry", "Category", "Criticality", "AgentSpec", "REGISTRY",
    # wrappers
    "stats", "validate", "all_agent_names", "get_agent",
    # backward compat
    "load_registry", "agent", "list_agents",
    "has_permission", "can_use_tool",
    "all_pipeline_ids", "all_pipelines", "pipeline",
]

__version__ = "3.4.0"
