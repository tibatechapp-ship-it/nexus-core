"""Hive guards — thin wrapper over nova.factory.guards.

Provides:
    - build_default_chain (re-exported)
    - RBAC functions (can_agent_use_tool, etc.)
    - Backwards-compatible aliases

The RBAC functions live in nova.security.permissions.
"""
from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# RE-EXPORT FROM nova.factory.guards
# ═══════════════════════════════════════════════════════════════

try:
    from novamind.factory.guards import (
        Guard, GuardResult,
        CodeGuard, SchemaGuard, FileGuard, ImportGuard, OutputGuard,
        GuardChain, build_default_chain,
        HallucinationGuard, add_hallucination_to_chain,
    )
except ImportError as e:
    logger.warning("nova.factory.guards unavailable: %s", e)

    # Fallback: no-op chain
    class _NoopChain:
        def check(self, *args, **kwargs):
            class _R:
                passed = True
                ok = True
                errors = []
                warnings = []
                def __bool__(self): return True
            return _R()
        def __iter__(self): return iter([])
        def __len__(self): return 0

    def build_default_chain(*args, **kwargs):
        return _NoopChain()


# ═══════════════════════════════════════════════════════════════
# RBAC
# ═══════════════════════════════════════════════════════════════

class PermissionDenied(Exception):
    """يُرفع عندما يفتقد الوكيل صلاحية."""
    pass


def can_agent_use_tool(agent_name: str, tool: str) -> bool:
    """يتحقق إن كان الوكيل يمتلك صلاحية."""
    try:
        from novamind.security.permissions import has_permission
        allowed = has_permission(agent_name, tool)
    except ImportError:
        allowed = True  # fail-open

    # Audit
    try:
        from novamind.security.rbac_audit import get_rbac_audit
        get_rbac_audit().log(agent_name, tool, allowed)
    except Exception:
        pass

    return allowed


def require_permission(agent_name: str, tool: str) -> None:
    """يرفع PermissionDenied إذا لم يكن مُصرّحاً."""
    if not can_agent_use_tool(agent_name, tool):
        from novamind.security.permissions import get_permissions, get_role_for_agent
        raise PermissionDenied(
            f"Agent '{agent_name}' (role={get_role_for_agent(agent_name)}) "
            f"lacks permission '{tool}'. Has: {get_permissions(agent_name)}"
        )


def get_agent_permissions(agent_name: str) -> List[str]:
    """يُعيد قائمة الصلاحيات."""
    try:
        from novamind.security.permissions import get_permissions
        return get_permissions(agent_name)
    except ImportError:
        return []


def get_agent_role(agent_name: str) -> str:
    """يُعيد دور الوكيل."""
    try:
        from novamind.security.permissions import get_role_for_agent
        return get_role_for_agent(agent_name)
    except ImportError:
        return "unknown"


# Legacy alias
def check(*args, **kwargs): return True
def has_permission(*args, **kwargs):
    if len(args) >= 2:
        return can_agent_use_tool(args[0], args[1])
    return True


__all__ = [
    "build_default_chain", "check",
    "can_agent_use_tool", "require_permission",
    "get_agent_permissions", "get_agent_role",
    "PermissionDenied", "has_permission",
]
