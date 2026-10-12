"""Unified Registry Core — يدمج nova.yaml + RBAC من registry_full_v2.

This is the SINGLE SOURCE OF TRUTH for:
- Agent metadata (from nova.yaml)
- RBAC permissions (from registry_full_v2)
- Tool capabilities
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DATA_DIR = Path(__file__).parent / "data"
_YAML = _DATA_DIR / "nova.yaml"


@lru_cache(maxsize=1)
def load_registry() -> dict:
    """Load the master registry from nova.yaml."""
    if not _YAML.exists():
        raise FileNotFoundError(f"❌ {_YAML} غير موجود")
    with open(_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_agent(name: str) -> dict:
    """Get agent metadata by canonical name or alias."""
    data = load_registry()
    if name in data["agents"]:
        return data["agents"][name]
    aliases = data.get("alias_index", {})
    if name in aliases:
        canonical = aliases[name]
        return data["agents"][canonical]
    raise KeyError(f"Agent '{name}' not found. Available: {len(data['agents'])}")


def list_agents() -> list[str]:
    """List all canonical agent names."""
    return list(load_registry()["agents"].keys())


def validate() -> list[str]:
    """Validate the registry. Returns list of errors."""
    errors = []
    data = load_registry()
    if "agents" not in data:
        errors.append("Missing 'agents' section")
        return errors
    for name, meta in data["agents"].items():
        for required in ("module", "class_name"):
            if required not in meta:
                errors.append(f"{name}: missing {required}")
    return errors


# ─── RBAC (from registry_full_v2) ───
def has_permission(agent: str, permission: str) -> bool:
    """Check RBAC permission for an agent."""
    try:
        from novamind.core.hive.factory.registry_full_v2 import (
            has_permission as _has_perm
        )
        return _has_perm(agent, permission)
    except ImportError:
        return True  # Permissive fallback


def can_use_tool(agent: str, tool: str) -> bool:
    """Check if agent can use a specific tool."""
    try:
        from novamind.core.hive.core.agents_registry import can_use_tool as _cut
        return _cut(agent, tool)
    except ImportError:
        return True


def stats() -> dict:
    """Get registry statistics."""
    data = load_registry()
    return data.get("summary", {})


__all__ = [
    "load_registry",
    "get_agent",
    "list_agents",
    "validate",
    "has_permission",
    "can_use_tool",
    "stats",
]

# ═══ Pipelines API ═══
def all_pipeline_ids() -> list[str]:
    """أسماء كل pipelines."""
    data = load_registry()
    return list(data.get("pipelines", {}).keys())


def all_pipelines() -> dict:
    """كل pipelines مع تفاصيلها."""
    data = load_registry()
    return dict(data.get("pipelines", {}))


def pipeline(pipeline_id: str) -> dict | None:
    """تفاصيل pipeline واحد."""
    data = load_registry()
    return data.get("pipelines", {}).get(pipeline_id)
