"""Shim → novamind.registry (backward compatibility)."""
from novamind.registry import *  # noqa: F401, F403
from novamind.registry import (  # noqa: F401
    agent,
    all_agent_names,
    all_agent_names_with_aliases,
    agents_by_category,
    agents_by_criticality,
    stats,
    validate,
)
