"""Adapter from the organization AgentRuntime to the coder engine connector API.

The coder engine deliberately depends on a tiny async generate protocol.
This adapter keeps provider selection, fallback, token accounting and run
recording inside AgentRuntime instead of creating a second provider path.
"""
from __future__ import annotations

import asyncio
from typing import Any

from src.org.agents import AgentRuntime, AgentSpec
from src.org.providers import ProviderError


class OrgRuntimeConnector:
    """Expose AgentRuntime as the coder engine's async connector.

    Calls are dispatched to a worker thread because AgentRuntime is synchronous
    and performs provider I/O. The engine receives the original provider text;
    JSON parsing and RepairPlan validation remain the coder engine's job.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        mission_id: str,
        max_tokens: int = 4000,
        max_retries: int = 1,
        timeout_s: float = 120.0,
    ) -> None:
        if not mission_id.strip():
            raise ValueError("mission_id must not be empty")
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.runtime = runtime
        self.mission_id = mission_id
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.usage_total = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        self.providers_used: set[str] = set()
        self.models_used: set[str] = set()

    @staticmethod
    def _role_for(prompt: str) -> str:
        lowered = prompt.lower()
        if "defect-discovery stage" in lowered:
            return "coder:detector"
        if "planning stage" in lowered:
            return "coder:planner"
        return "coder:worker"

    async def generate(self, prompt: str) -> dict[str, Any]:
        """Return the coder connector response shape without hiding failures."""
        if not isinstance(prompt, str) or not prompt.strip():
            return {"ok": False, "error": "prompt must not be empty"}
        spec = AgentSpec(
            role=self._role_for(prompt),
            dept="development",
            mission_id=self.mission_id,
            models=self.runtime.pool.models(),
            max_retries=self.max_retries,
            timeout_s=self.timeout_s,
            max_tokens=self.max_tokens,
        )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self.runtime.complete, spec, prompt),
                timeout=self.timeout_s,
            )
        except (ProviderError, ValueError, asyncio.TimeoutError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}
        self.usage_total["tokens_in"] += response.usage.in_tokens
        self.usage_total["tokens_out"] += response.usage.out_tokens
        self.usage_total["cost_usd"] += response.usage.cost_usd
        self.providers_used.add(response.provider)
        self.models_used.add(response.model)
        return {
            "ok": True,
            "reply": response.text,
            "usage": {
                "tokens_in": response.usage.in_tokens,
                "tokens_out": response.usage.out_tokens,
                "cost_usd": response.usage.cost_usd,
            },
            "provider": response.provider,
            "model": response.model,
        }
