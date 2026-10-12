"""A2A HTTP Server — exposes NovaMind agents via A2A protocol."""
import sys
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from novamind.core.a2a.agent_card import AgentCard, AgentSkill

logger = logging.getLogger("core.a2a.server")


# ═══════════════════════════════════════════════════════════
# Request/Response models
# ═══════════════════════════════════════════════════════════
if FASTAPI_AVAILABLE:
    class TaskSendRequest(BaseModel):
        skill: str  # agent name
        text: str   # code to analyze
        filename: str = "code.py"
        task_id: Optional[str] = None

    class TaskResponse(BaseModel):
        task_id: str
        status: str
        result: Optional[Dict] = None
        error: Optional[str] = None
        created_at: str


# ═══════════════════════════════════════════════════════════
# A2A Server
# ═══════════════════════════════════════════════════════════
class A2AServer:
    """A2A server exposing NovaMind agents."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8000, factory=None):
        self.host = host
        self.port = port
        self._factory = factory
        self._tasks: Dict[str, Dict] = {}

    @property
    def factory(self):
        if self._factory is None:
            from novamind.agents.factory import AgentFactory
            self._factory = AgentFactory()
        return self._factory

    def build_agent_card(self) -> Dict:
        """Build A2A Agent Card for NovaMind."""
        skills = []
        for name in sorted(self.factory.list_available()):
            skills.append(AgentSkill(
                id=name,
                name=name,
                description=f"NovaMind agent: {name}",
                tags=["code-analysis", "novamind"],
            ))

        card = AgentCard(
            name="NovaMind",
            description="52 specialized code intelligence agents",
            version="8.0.0",
            url=f"http://{self.host}:{self.port}",
            capabilities={"streaming": False, "pushNotifications": False},
            skills=skills,
            provider={"organization": "TibaTech", "url": "https://github.com/tibatechapp-ship-it/novamind-core"},
        )
        return card.to_dict()

    def handle_task(self, skill: str, text: str,
                    filename: str = "code.py",
                    task_id: Optional[str] = None) -> Dict:
        """Handle an A2A task."""
        task_id = task_id or str(uuid.uuid4())

        if skill not in self.factory.list_all():
            return {
                "task_id": task_id,
                "status": "failed",
                "error": f"Unknown skill: {skill}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            result = self.factory.call(skill, code=text, filename=filename)
        except TypeError:
            result = self.factory.call(skill, code=text)
        except Exception as e:
            return {
                "task_id": task_id,
                "status": "failed",
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        response = {
            "task_id": task_id,
            "status": "completed",
            "result": result,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._tasks[task_id] = response
        return response

    def get_task(self, task_id: str) -> Optional[Dict]:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)


# ═══════════════════════════════════════════════════════════
# FastAPI app
# ═══════════════════════════════════════════════════════════
def create_app() -> "FastAPI":
    """Create FastAPI app with A2A endpoints."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI not installed. Run: pip install fastapi uvicorn")

    app = FastAPI(title="NovaMind A2A Server", version="8.0.0")
    server = A2AServer()

    @app.get("/.well-known/agent.json")
    def agent_card():
        return server.build_agent_card()

    @app.post("/tasks/send", response_model=TaskResponse)
    def send_task(req: TaskSendRequest):
        result = server.handle_task(
            skill=req.skill, text=req.text,
            filename=req.filename, task_id=req.task_id,
        )
        if result["status"] == "failed":
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/tasks/{task_id}", response_model=TaskResponse)
    def get_task(task_id: str):
        task = server.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get("/health")
    def health():
        return {"status": "ok", "agents": len(server.factory.list_available())}

    return app


__all__ = ["A2AServer", "create_app"]


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
