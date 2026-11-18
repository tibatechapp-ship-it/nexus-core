"""NovaMind guard exports and the single canonical RBAC bridge.

This package is the import target for all execution paths. It delegates
authorization to novamind.security.permissions and never grants access when
that policy cannot be imported.
"""
from __future__ import annotations

from typing import List

from novamind.factory.guards.base import Guard, GuardResult
from novamind.factory.guards.code_guard import CodeGuard
from novamind.factory.guards.schema_guard import SchemaGuard
from novamind.factory.guards.file_guard import FileGuard
from novamind.factory.guards.import_guard import ImportGuard
from novamind.factory.guards.output_guard import OutputGuard
from novamind.factory.guards.chain import GuardChain, build_default_chain
from novamind.factory.guards.hallucination_guard import (
    HallucinationGuard,
    add_hallucination_to_chain,
)


class PermissionDenied(PermissionError):
    """Raised when an agent lacks an explicit permission."""


def can_agent_use_tool(agent_name: str, tool: str) -> bool:
    """Return the canonical RBAC decision; missing policy means deny."""
    try:
        from novamind.security.permissions import has_permission

        return bool(has_permission(agent_name, tool))
    except Exception:
        return False


def require_permission(agent_name: str, tool: str) -> None:
    """Raise unless the canonical RBAC policy explicitly allows the action."""
    if not can_agent_use_tool(agent_name, tool):
        raise PermissionDenied(
            f"Agent {agent_name!r} is not authorized for {tool!r}"
        )


def get_agent_permissions(agent_name: str) -> List[str]:
    """Return explicit permissions, or an empty list if policy is unavailable."""
    try:
        from novamind.security.permissions import get_permissions

        return list(get_permissions(agent_name))
    except Exception:
        return []


def get_agent_role(agent_name: str) -> str:
    """Return the resolved role, or unknown if it cannot be resolved."""
    try:
        from novamind.security.permissions import get_role_for_agent

        return get_role_for_agent(agent_name)
    except Exception:
        return "unknown"


__all__ = [
    "Guard", "GuardResult",
    "CodeGuard", "SchemaGuard", "FileGuard", "ImportGuard", "OutputGuard",
    "GuardChain", "build_default_chain",
    "HallucinationGuard", "add_hallucination_to_chain",
    "can_agent_use_tool", "require_permission",
    "get_agent_permissions", "get_agent_role", "PermissionDenied",
]
