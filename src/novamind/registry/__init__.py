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
    """إحصائيات المصدر المعتمد؛ لا تُستبدل بسجل توافق قديم."""
    if not (_CORE_AVAILABLE and _core_stats):
        raise RuntimeError("canonical NovaMind registry is unavailable")
    return _core_stats()


def validate() -> list:
    """فحص المصدر المعتمد؛ غيابه خطأ وليس نجاحاً فارغاً."""
    if not (_CORE_AVAILABLE and _core_validate):
        return ["canonical NovaMind registry is unavailable"]
    try:
        return _core_validate()
    except Exception as e:
        return [f"canonical registry validation failed: {e}"]


def all_agent_names() -> list:
    """أسماء الوكلاء من nova.yaml حصراً."""
    if not (_CORE_AVAILABLE and _core_list_agents):
        raise RuntimeError("canonical NovaMind registry is unavailable")
    return _core_list_agents()


def get_agent(name: str) -> dict:
    """تفاصيل وكيل واحد من المصدر المعتمد حصراً."""
    if not (_CORE_AVAILABLE and _core_get_agent):
        raise RuntimeError("canonical NovaMind registry is unavailable")
    return _core_get_agent(name)


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
    return False


def can_use_tool(agent_name: str, tool: str) -> bool:
    """فحص استخدام أداة."""
    if _CORE_AVAILABLE and _core_can_use_tool:
        return _core_can_use_tool(agent_name, tool)
    return False


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
    "all_pipeline_ids", "all_pipelines", "pipeline", "agents_by_category", "agents_by_criticality", "all_agent_names_with_aliases",
]


# ═══════════════════════════════════════════════════════════════
# Backward-compatible aliases (required by _registry shim)
# ═══════════════════════════════════════════════════════════════

def agents_by_category(category) -> list:
    """كل الوكلاء في فئة معينة.
    
    Args:
        category: Category enum أو str مثل "code", "security"
    
    Returns:
        قائمة بأسماء الوكلاء
    """
    from novamind.registry.v2 import Category
    if isinstance(category, str):
        try:
            category = Category(category)
        except ValueError:
            return []
    return REGISTRY.list_by_category(category)


def agents_by_criticality(criticality) -> list:
    """كل الوكلاء حسب مستوى الأهمية.
    
    Args:
        criticality: Criticality enum أو str مثل "core", "standard", "optional"
    
    Returns:
        قائمة بأسماء الوكلاء
    """
    from novamind.registry.v2 import Criticality
    if isinstance(criticality, str):
        try:
            criticality = Criticality(criticality)
        except ValueError:
            return []
    return REGISTRY.list_by_criticality(criticality)


def all_agent_names_with_aliases() -> list:
    """كل أسماء الوكلاء + aliases.
    
    Returns:
        قائمة موحدة من الأسماء الرسمية + المرادفات
    """
    names = all_agent_names()
    aliases = alias_index()
    return names + [k for k in aliases.keys() if k not in names]


__version__ = "3.4.0"
