"""Compatibility adapter backed by NovaMind's canonical agent registry.

This module intentionally contains no independent agent registry and no
permissive mock identities. Unknown agents and unavailable metadata fail closed.
"""
from __future__ import annotations

from typing import Any


def get_agent(name: str) -> dict[str, Any]:
    """Resolve a real registered agent into the legacy executor shape."""
    from novamind.registry import get_agent as get_metadata
    from novamind.security.permissions import get_permissions, get_role_for_agent

    metadata = get_metadata(name)
    return {
        "name": name,
        "specialty": metadata.get("category", "general"),
        "capabilities": list(metadata.get("capabilities", [])),
        "tools": list(metadata.get("tools", [])),
        "permissions": get_permissions(name),
        "system_prompt": metadata.get("description", ""),
        "role": get_role_for_agent(name),
    }


def can_use_tool(agent: str, tool: str) -> bool:
    """Check access against the canonical RBAC policy."""
    from novamind.security.permissions import has_permission
    return bool(has_permission(agent, tool))


def has_permission(agent: str, action: str) -> bool:
    """Compatibility alias for canonical RBAC."""
    return can_use_tool(agent, action)


def record_tool_call(*args: Any, **kwargs: Any) -> None:
    """Compatibility hook; durable tool auditing is owned by the executor."""
    return None
