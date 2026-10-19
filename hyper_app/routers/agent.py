"""Hyper-Agent 2.0 — HTTP entry point (BYOK-aware)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hyper_agent import autonomous_workflow_hyper

router = APIRouter()


class AgentStartRequest(BaseModel):
    """POST /api/agent/start body — user_config selects the BYOK provider."""

    goal: str
    max_iterations: int = Field(default=5, ge=1, le=20)
    user_config: Optional[Dict[str, Any]] = None


@router.post("/api/agent/start")
async def start_agent(req: AgentStartRequest) -> Dict[str, Any]:
    """Run the autonomous loop once per iteration until done/stalled/verify_fail."""
    state = await autonomous_workflow_hyper(
        goal=req.goal,
        max_iterations=req.max_iterations,
        user_config=req.user_config or {"provider": "ollama"},
    )
    return {
        "ok": state.get("status") == "done",
        "status": state.get("status"),
        "state": state,
    }
