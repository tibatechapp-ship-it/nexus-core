"""
NovaMind Unified Agent — v10.0

Integrates:
- NovaMind core (52 agents, Orchestrator, MCP, A2A)
- LangGraph (ReAct reasoning)
- LSP (code analysis)
- Web UI (Chat + IDE)
- LLM Router (free: Gemini/Groq)

Usage:
    python unified_agent.py
    open http://localhost:8000
"""
import os
import sys
import json
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Optional

# ═══════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# FastAPI
from fastapi import FastAPI
from fastapi import HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

# NovaMind core
from core.llm_router import LLMRouter
from core.orchestrator import Orchestrator, TASK_TEMPLATES
from core.observability import metrics
from core.mcp_server import NovaMindMCP
from core.loop_engine import LoopEngine, Goal

# ═══════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = Path(os.getenv("NOVAMIND_PROJECT_ROOT", str(ROOT))).resolve()
PORT = int(os.getenv("NOVAMIND_PORT", "8000"))
MAX_FILE_SIZE = 50000

IGNORE_DIRS = {
    '.git', 'node_modules', 'venv', '__pycache__', '.idea', '.vscode',
    'dist', 'build', '.novamind', '.pytest_cache', '.mypy_cache',
}

# ═══════════════════════════════════════════════════════════
# Safe path
# ═══════════════════════════════════════════════════════════
def safe_path(path: str) -> Path:
    p = (PROJECT_ROOT / path).resolve()
    try:
        p.relative_to(PROJECT_ROOT)
    except ValueError:
        raise ValueError(f"'{path}' outside project")
    return p


def get_file_tree(directory: Path, depth: int = 0, max_depth: int = 3) -> List[Dict]:
    """Recursive file tree."""
    if depth > max_depth:
        return []
    tree = []
    try:
        entries = sorted(
            directory.iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )
    except PermissionError:
        return []

    for entry in entries:
        if entry.name in IGNORE_DIRS or entry.name.startswith('.'):
            continue
        try:
            rel = str(entry.relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            continue

        if entry.is_dir():
            tree.append({
                "type": "dir", "name": entry.name, "path": rel,
                "children": get_file_tree(entry, depth + 1, max_depth),
            })
        else:
            tree.append({"type": "file", "name": entry.name, "path": rel})
    return tree


# ═══════════════════════════════════════════════════════════
# LLM chat (using NovaMind router — free providers)
# ═══════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are "NovaMind" — an expert AI Software Engineer in an integrated IDE.

You have access to:
- 52 specialized code analysis agents (security, quality, data, devops, frontend, ai)
- Web search, file read/write, git operations, Python execution
- Semantic search across the codebase

## Workflow
1. Understand the task (read files or list issues).
2. Search relevant code with semantic_search.
3. Edit files with write_project_file.
4. Test with run_python.
5. Commit with run_git.

## Style
- Reply in Arabic if user wrote in Arabic.
- Use Markdown. Code blocks in English.
- Be concise.
"""


class UnifiedChat:
    """Chat interface using NovaMind's LLM Router."""

    def __init__(self):
        self.router = LLMRouter()
        self.mcp = NovaMindMCP()
        self.orchestrator = Orchestrator()
        self.loop_engine = LoopEngine()
        self.conversations: Dict[str, List[Dict]] = {}

    def get_history(self, thread_id: str) -> List[Dict]:
        return self.conversations.setdefault(thread_id, [])

    async def chat_stream(self, message: str, thread_id: str):
        """Stream via Proactive Pipeline: Gatekeeper -> Planner -> ReAct -> PreCheck."""
        import asyncio as _aio
        import json as _json

        try:
            if not hasattr(self, "_react_loop"):
                from core.react_loop import ReactLoop
                self._react_loop = ReactLoop(
                    router=self.router,
                    tools=REACT_TOOLS if "REACT_TOOLS" in globals() else {},
                    max_iterations=5,
                )
            proactive_pipeline.set_react_loop(self._react_loop)
        except Exception as e:
            yield "data: " + _json.dumps({"type": "error", "content": "Init error: " + str(e)}, ensure_ascii=False) + chr(10) + chr(10)
            yield "data: [DONE]" + chr(10) + chr(10)
            return

        loop = _aio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: proactive_pipeline.execute(message)
            )
        except Exception as e:
            yield "data: " + _json.dumps({"type": "error", "content": "Pipeline error: " + str(e)}, ensure_ascii=False) + chr(10) + chr(10)
            yield "data: [DONE]" + chr(10) + chr(10)
            return

        gate = result.gatekeeper if isinstance(result.gatekeeper, dict) else {}
        if result.status == "blocked" or gate.get("decision") == "block":
            yield "data: " + _json.dumps({"type": "error", "content": result.answer or "Blocked"}, ensure_ascii=False) + chr(10) + chr(10)
            yield "data: [DONE]" + chr(10) + chr(10)
            return

        plan = result.plan if isinstance(result.plan, dict) else {}
        if plan:
            plan_txt = "Plan: " + str(plan.get("category", "?")) + " / " + str(plan.get("complexity", "?"))
            yield "data: " + _json.dumps({"type": "plan", "content": plan_txt}, ensure_ascii=False) + chr(10) + chr(10)

        answer = result.answer or "(no answer)"
        for i in range(0, len(answer), 24):
            yield "data: " + _json.dumps({"type": "chunk", "content": answer[i:i+24]}, ensure_ascii=False) + chr(10) + chr(10)
            await _aio.sleep(0.02)

        pc = result.pre_check if isinstance(result.pre_check, dict) else {}
        if pc and pc.get("decision") and pc["decision"] != "clean":
            yield "data: " + _json.dumps({"type": "pre_check", "decision": pc["decision"]}, ensure_ascii=False) + chr(10) + chr(10)

        yield "data: [DONE]" + chr(10) + chr(10)

    def analyze(self, task: str, code: str) -> Dict:
        """Run multi-agent analysis."""
        result = self.orchestrator.run(task=task, code=code, mode="parallel")
        return result.to_dict()

    def run_until(self, description: str, agent: str, code: str,
                  max_iter: int = 5) -> Dict:
        """Run agent until success."""
        goal = Goal(description=description, max_iterations=max_iter)
        result = self.loop_engine.run_until(
            goal=goal, agent_name=agent, agent_kwargs={"code": code},
        )
        return result.to_dict()


# ═══════════════════════════════════════════════════════════
# FastAPI
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# ReAct Tools
# ═══════════════════════════════════════════════════════════
import subprocess
import shlex


def tool_analyze_code(task: str = "security_audit", code: str = "") -> str:
    if not code:
        return "Error: 'code' argument required"
    try:
        result = unified_orch.run(task=task, code=code, mode="parallel")
        s = result.summary
        if s.get("total_issues", 0) == 0:
            return f"No issues found in {task}."
        lines = [f"Found {s['total_issues']} issues:"]
        for sev, cnt in s.get("issues_by_severity", {}).items():
            lines.append(f"  - {sev}: {cnt}")
        for r in result.results:
            res = r.get("result", {})
            for issue in (res.get("issues") or [])[:3]:
                lines.append(
                    f"  - [{issue.get('severity', '?')}] "
                    f"{issue.get('description', '?')} "
                    f"(line {issue.get('line', '?')})"
                )
        return "\n".join(lines)
    except Exception as e:
        return f"Analyze error: {type(e).__name__}: {e}"


def tool_read_file(path: str = "") -> str:
    if not path:
        return "Error: 'path' argument required"
    try:
        p = safe_path(path)
        if not p.exists():
            return f"File not found: {path}"
        return p.read_text(encoding="utf-8", errors="replace")[:5000]
    except ValueError as e:
        return f"Access denied: {e}"
    except Exception as e:
        return f"Error: {e}"


def tool_write_file(path: str = "", content: str = "") -> str:
    if not path:
        return "Error: 'path' argument required"
    try:
        p = safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Saved {path} ({len(content)} chars)"
    except ValueError as e:
        return f"Access denied: {e}"
    except Exception as e:
        return f"Error: {e}"


def tool_list_files(path: str = ".") -> str:
    try:
        p = safe_path(path)
        if not p.exists():
            return f"Path not found: {path}"
        if not p.is_dir():
            return f"Not a directory: {path}"
        entries = []
        for e in sorted(p.iterdir())[:50]:
            if e.name.startswith("."):
                continue
            prefix = "DIR" if e.is_dir() else "FILE"
            entries.append(f"{prefix} {e.name}")
        return "\n".join(entries) if entries else "Empty directory"
    except Exception as e:
        return f"Error: {e}"


def tool_git_command(command: str = "") -> str:
    allowed = {"status", "log", "diff", "branch", "show"}
    try:
        parts = shlex.split(command)
    except ValueError:
        return "Invalid command syntax"
    if not parts or parts[0] != "git":
        return "Command must start with 'git'"
    if len(parts) < 2 or parts[1] not in allowed:
        return f"Only allowed: {', '.join(sorted(allowed))}"
    try:
        r = subprocess.run(
            parts, cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=10,
        )
        return ((r.stdout or "") + (r.stderr or ""))[:3000]
    except Exception as e:
        return f"Git error: {e}"


REACT_TOOLS = {
    "analyze_code": tool_analyze_code,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_files": tool_list_files,
    "git_command": tool_git_command,
}

from core.orchestrator import Orchestrator as _Orch
from core.proactive_pipeline import proactive_pipeline
unified_orch = _Orch()


app = FastAPI(title="NovaMind Unified", version="10.0.0")


unified = UnifiedChat()


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class FileRequest(BaseModel):
    path: str
    content: str


class AnalyzeRequest(BaseModel):
    task: str = "security_audit"
    code: str


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    ui_path = ROOT / "web" / "unified_ui.html"
    if ui_path.exists():
        return ui_path.read_text(encoding="utf-8")
    return "<h1>NovaMind Unified</h1><p>UI not found. Create web/unified_ui.html</p>"


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "10.0.0",
        "project_root": str(PROJECT_ROOT),
        "agents": len(unified.mcp.factory.list_available()),
        "templates": list(TASK_TEMPLATES.keys()),
    }


@app.get("/api/workspace/tree")
async def get_tree():
    return JSONResponse(content=get_file_tree(PROJECT_ROOT))


@app.get("/api/workspace/file")
async def read_file(path: str = Query(...)):
    try:
        content = safe_path(path).read_text(encoding="utf-8", errors="replace")
        return {"content": content[:MAX_FILE_SIZE]}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/workspace/file")
async def write_file(req: FileRequest):
    try:
        p = safe_path(req.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(req.content, encoding="utf-8")
        return {"status": "saved", "path": req.path}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    async def event_gen():
        async for event in unified.chat_stream(req.message, req.thread_id):
            yield event
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/analyze")
async def analyze_endpoint(req: AnalyzeRequest):
    result = unified.analyze(task=req.task, code=req.code)
    return result


@app.get("/api/agents")
async def list_agents():
    """List all 52 agents as MCP tools."""
    return unified.mcp.list_tools()


@app.get("/api/metrics")
async def get_metrics():
    return metrics.snapshot()


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════
# Pipeline Control Endpoints
# ═══════════════════════════════════════════════════════════
@app.get("/api/pipeline/status")
async def pipeline_status():
    from core.security_gatekeeper import gatekeeper
    from core.task_planner import planner
    from core.pre_check import pre_check
    return {
        "gatekeeper": True,
        "planner": True,
        "pre_check": True,
        "status": "operational",
    }

@app.post("/api/security/check")
async def security_check(req: dict):
    from core.security_gatekeeper import gatekeeper
    text = req.get("text", "")
    check_type = req.get("type", "request")
    if check_type == "code":
        from core.pre_check import pre_check
        return pre_check.check(text).to_dict()
    return gatekeeper.analyze(text).to_dict()

@app.post("/api/pipeline/plan")
async def pipeline_plan(req: dict):
    from core.task_planner import planner
    plan = planner.plan(req.get("message", ""))
    return plan.to_dict()

@app.get("/api/security/metrics")
async def security_metrics():
    from core.security_gatekeeper import gatekeeper
    return gatekeeper.get_metrics()


def main():
    print("=" * 60)
    print("  NovaMind Unified v10.0")
    print("=" * 60)
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Port: {PORT}")
    print(f"  Agents: {len(unified.mcp.factory.list_available())}")
    print(f"  LLM providers: {len(unified.router.providers)}")
    for p in unified.router.providers:
        print(f"    - {p.name}: {p.models}")
    print()
    print(f"  UI: http://localhost:{PORT}")
    print("=" * 60)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")



@app.post("/api/pipeline/run")
async def api_pipeline_run(req: dict):
    """Run full Proactive Pipeline on a request."""
    message = req.get("message", "")
    try:
        result = proactive_pipeline.execute(message)
        return {
            "status": result.status,
            "answer": (result.answer or "")[:500],
            "gatekeeper": result.gatekeeper,
            "plan": result.plan,
            "pre_check": result.pre_check,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}




# ═══════════════════════════════════════════════════════
# SSE Stream endpoint
# ═══════════════════════════════════════════════════════
class _StreamRequest(BaseModel):
    prompt: str = ""
    message: str = ""
    thread_id: str = "default"

@app.post("/api/pipeline/run/stream")
async def pipeline_stream(req: _StreamRequest):
    import asyncio as _aio
    from fastapi.responses import StreamingResponse as _SR

    user_message = (req.prompt or req.message).strip() or "(empty)"

    async def _gen():
        try:
            # Ensure ReactLoop is wired
            if getattr(proactive_pipeline, "_react_loop", None) is None:
                from core.react_loop import ReactLoop
                if getattr(unified, "_react_loop", None) is None:
                    unified._react_loop = ReactLoop(
                        router=unified.router,
                        tools=REACT_TOOLS,
                        max_iterations=3,
                    )
                proactive_pipeline.set_react_loop(unified._react_loop)

            loop = _aio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: proactive_pipeline.execute(user_message)
            )

            if result.gatekeeper:
                yield "data: " + json.dumps({
                    "type": "gatekeeper",
                    "decision": result.gatekeeper.get("decision"),
                    "reason": (result.gatekeeper.get("reason") or "")[:200],
                }, ensure_ascii=False) + chr(10) + chr(10)

            if result.status == "blocked":
                yield "data: " + json.dumps({
                    "type": "blocked",
                    "output": result.answer,
                }, ensure_ascii=False) + chr(10) + chr(10)
                yield "data: [DONE]" + chr(10) + chr(10)
                return

            if result.plan:
                yield "data: " + json.dumps({
                    "type": "plan",
                    "category": result.plan.get("category"),
                    "complexity": result.plan.get("complexity"),
                }, ensure_ascii=False) + chr(10) + chr(10)

            answer = result.answer or ""
            for i in range(0, len(answer), 24):
                yield "data: " + json.dumps(
                    {"output": answer[i:i+24]},
                    ensure_ascii=False,
                ) + chr(10) + chr(10)
                await _aio.sleep(0.02)

            if result.pre_check:
                yield "data: " + json.dumps({
                    "type": "pre_check",
                    "decision": result.pre_check.get("decision"),
                }, ensure_ascii=False) + chr(10) + chr(10)

        except Exception as e:
            yield "data: " + json.dumps(
                {"type": "error", "output": "Pipeline error: " + str(e)},
                ensure_ascii=False,
            ) + chr(10) + chr(10)

        yield "data: [DONE]" + chr(10) + chr(10)

    return _SR(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

if __name__ == "__main__":
    main()
