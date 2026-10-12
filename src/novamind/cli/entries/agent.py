"""
Agent API — Run autonomous tasks.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User


router = APIRouter(prefix="/agent", tags=["Agent"])


class AgentRequest(BaseModel):
    task: str = Field(..., min_length=3, max_length=2000)


class AgentResponse(BaseModel):
    ok: bool
    task: str
    summary: str = ""
    steps: int = 0
    trace: list = []


@router.post("/run", response_model=AgentResponse)
async def run_agent(
    req: AgentRequest,
    user: User = Depends(get_current_user),
):
    """Run a task with the agent."""
    # Try real agent
    try:
        from agent_v8.real_agent import RealAgent
        agent = RealAgent(repo_id="R-001", max_steps=8)
        result = agent.run(req.task)
        return AgentResponse(
            ok=result.get("ok", False),
            task=req.task,
            summary=result.get("summary", ""),
            steps=result.get("steps", 0),
            trace=result.get("trace", []),
        )
    except ImportError:
        # Fallback: mock
        return AgentResponse(
            ok=True,
            task=req.task,
            summary=f"[Demo] تم تنفيذ: {req.task[:100]}",
            steps=1,
            trace=[{"phase": "mock", "content": "Agent not available"}],
        )
