"""Compatibility facade for the canonical NovaMind executor.

The implementation lives exclusively in :mod:`novamind.factory.executor`.
This module preserves historical import paths while delegating execution,
authorization, parsing, guards, and result contracts to that implementation.
"""
from __future__ import annotations

from typing import Any

from novamind.factory import executor as _canonical

# Public compatibility symbols. Keep these names importable for older callers.
SYSTEM_BASE = _canonical.SYSTEM_BASE
TASK_TEMPLATES = _canonical.TASK_TEMPLATES
DEFAULT_TEMPLATE = _canonical.DEFAULT_TEMPLATE
PYTHON_INDICATORS = _canonical.PYTHON_INDICATORS
SecurityError = _canonical.SecurityError
build_prompt = _canonical.build_prompt
parse_output = _canonical.parse_output
pick_llm_for = _canonical.pick_llm_for
execute_agent_sync = _canonical.execute_agent_sync

# These two names remain patchable for integrations/tests that historically
# patched the hive module. They only provide the optional provider injection;
# all actual work still runs in the canonical executor.
make_llm_call = _canonical.make_llm_call
is_llm_available = _canonical.is_llm_available


async def execute_agent(
    agent_id: str,
    task: str,
    ctx: Any = None,
    task_id: str | None = None,
    max_retries: int = 1,
    llm_call: Any = None,
) -> dict[str, Any]:
    """Delegate to the one canonical executor implementation."""
    availability = is_llm_available
    provider_available = availability() if callable(availability) else bool(availability)
    if llm_call is None and provider_available:
        llm_call = make_llm_call()
    return await _canonical.execute_agent(
        agent_id=agent_id,
        task=task,
        ctx=ctx,
        task_id=task_id,
        max_retries=max_retries,
        llm_call=llm_call,
    )


__all__ = [
    "SYSTEM_BASE",
    "TASK_TEMPLATES",
    "DEFAULT_TEMPLATE",
    "PYTHON_INDICATORS",
    "SecurityError",
    "build_prompt",
    "parse_output",
    "pick_llm_for",
    "execute_agent",
    "execute_agent_sync",
    "make_llm_call",
    "is_llm_available",
]
