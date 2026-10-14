"""Nexus-Core Web Dashboard."""
from __future__ import annotations
import os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# ═══ تحميل .env ═══
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Nexus-Core Dashboard", version="0.12.0")


class AgentRunRequest(BaseModel):
    agent: str
    prompt: str
    use_rag: bool = True

class RAGAddRequest(BaseModel):
    text: str

class CouncilRequest(BaseModel):
    question: str


def _setup_mock():
    from novamind.core.llm_router import LLMRouter
    def mock_gen(self, prompt="", system="", **kw):
        s = str(system); p = str(prompt)
        is_debate = "راجع" in p
        if "أنت الناقد" in s:
            t = "بعد المراجعة: متسقتان. مقبول." if is_debate else "أراجع الحجتين. مقبول."
        elif "أنت المحلل المتشكك" in s:
            t = "خطر: نقص السياق الأمني." if is_debate else "خطر: 3 مخاوف أمنية."
        elif "أنت المحلل المدافع" in s:
            t = "آمن: يمكن التخفيف." if is_debate else "آمن: الطلب مقبول."
        else:
            t = f"[Mock] {p[:80]}"
        return {"ok": True, "text": t, "provider": "mock", "elapsed": 0.01}
    LLMRouter.generate = mock_gen
    LLMRouter.generate_for_task = lambda self, *a, **kw: mock_gen(self, *a, **kw)
    LLMRouter._load_from_env = lambda self: setattr(self, 'providers', [])
    LLMRouter._cooldown_provider = lambda self, n, seconds=300: None
    LLMRouter._is_cooled_down = lambda self, n: True

# _setup_mock()  # ═══ مُعطّل — نستخدم LLM حقيقي


# ═══ Cache للحالة ═══
_status_cache = {"data": None, "ts": 0}

@app.get("/api/status")
def status():
    import time
    now = time.time()
    # ═══ استخدام cache إذا مر أقل من 30 ثانية ═══
    if _status_cache["data"] and (now - _status_cache["ts"] < 30):
        return _status_cache["data"]

    from nova.registry import REGISTRY
    try:
        from src.memory.agent_rag_bridge import get_bridge
        b = get_bridge()
        total = len(b.rag.store._conn.execute(f"SELECT * FROM {b.rag.store.table}_meta").fetchall())
    except Exception:
        total = 0

    result = {"version": "0.12.0", "agents": len(REGISTRY), "rag_docs": total}
    _status_cache["data"] = result
    _status_cache["ts"] = now
    return result


@app.get("/api/agents")
def list_agents():
    from nova.registry import REGISTRY, agents_by_category
    r = {}
    for cat in ['code','security','quality','infra','data','ui','research','meta']:
        r[cat] = agents_by_category(cat)
    return {"total": len(REGISTRY), "by_category": r}


@app.post("/api/agent/run")
def run_agent(req: AgentRunRequest):
    try:
        from nova.registry import REGISTRY
        agent = REGISTRY.load_agent(req.agent)
        methods = ["build","run","execute","analyze","fix","review","generate"]
        method = next((m for m in methods if hasattr(agent, m)), None)
        if not method:
            raise HTTPException(400, f"لا توجد طريقة للوكيل {req.agent}")
        prompt = req.prompt
        if req.use_rag:
            try:
                from src.memory.agent_rag_bridge import get_bridge
                b = get_bridge()
                enriched = b.enrich_prompt(prompt, k=3)
                if enriched != prompt: prompt = enriched
            except Exception: pass
        start = time.time()
        result = getattr(agent, method)(prompt)
        return {"ok": True, "agent": req.agent, "method": method,
                "result": str(result)[:3000], "elapsed": time.time() - start}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/rag/add")
def rag_add(req: RAGAddRequest):
    from src.memory.agent_rag_bridge import get_bridge
    b = get_bridge()
    return {"ok": True, "doc_id": b.remember(req.text)}


@app.get("/api/rag/query")
def rag_query(q: str, k: int = 5):
    from src.memory.agent_rag_bridge import get_bridge
    b = get_bridge()
    results = b.recall(q, k=k)
    return {"ok": True, "query": q,
            "results": [{"id": r.id, "text": r.text, "distance": r.distance} for r in results]}


@app.post("/api/council/deliberate")
def council_deliberate(req: CouncilRequest):
    try:
        import src.nexus
        from src.council.rag_bridge import get_council_bridge
        b = get_council_bridge()
        b.engine.MAX_ROUNDS = 1
        result = b.deliberate_with_memory(req.question)
        return {"ok": True, "verdict": result.verdict, "score": result.score,
                "rounds": result.rounds, "consensus": result.consensus,
                "elapsed": result.elapsed,
                "transcript": [{"phase": e["phase"], "member": e["member"], "response": e["response"][:500]} for e in result.transcript],
                "security_events": result.security_events}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══ Topics ═══
@app.get("/api/council/topics")
def list_topics():
    try:
        from src.council.topics import list_categories
        return {"ok": True, "categories": list_categories()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/council/topic")
def run_topic(req: CouncilRequest):
    try:
        from src.council.topics import get_topic
        t = get_topic(req.question)  # نستخدم حقل question كـ topic_id
        if not t:
            return {"ok": False, "error": "topic not found"}
        import src.nexus
        from src.council.rag_bridge import get_council_bridge
        b = get_council_bridge()
        result = b.deliberate_with_memory(t.question)
        return {
            "ok": True,
            "topic_id": t.id,
            "title": t.title,
            "verdict": result.verdict,
            "score": result.score,
            "rounds": result.rounds,
            "elapsed": result.elapsed,
            "transcript": [
                {"phase": e["phase"], "member": e["member"],
                 "response": e["response"][:500]}
                for e in result.transcript
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/council/history")
def council_history():
    try:
        from src.council.history import get_history
        h = get_history()
        return {"ok": True, "stats": h.stats(), "recent": h.list_recent(10)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══ Cache ═══
@app.get("/api/cache/stats")
def cache_stats():
    try:
        from src.council.cache import get_cache
        return {"ok": True, "stats": get_cache().stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/cache/clear")
def cache_clear():
    try:
        from src.council.cache import get_cache
        count = get_cache().clear()
        return {"ok": True, "cleared": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══ Metrics ═══
@app.get("/api/metrics/today")
def metrics_today():
    try:
        from src.nexus.monitoring import get_monitor
        return {"ok": True, "stats": get_monitor().get_today_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/metrics/clear")
def metrics_clear():
    try:
        from src.nexus.monitoring import get_monitor
        count = get_monitor().clear_today()
        return {"ok": True, "cleared": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return DASHBOARD


# ═══ Smart Router Endpoint ═══
class SmartRequest(BaseModel):
    prompt: str
    force_strategy: str = None


@app.post("/api/smart/run")
def smart_run(req: SmartRequest):
    """يستخدم Smart Router لاختيار الاستراتيجية المثلى."""
    try:
        import src.nexus  # تفعيل monitoring
        from src.orchestrator.supervisor import Supervisor
        
        sup = Supervisor(use_rag=True, verbose=False)
        result = sup.execute(req.prompt, force_strategy=req.force_strategy)
        
        return {
            "ok": result["ok"],
            "decision": result["decision"],
            "results": [
                {
                    "agent": r.get("agent", "?"),
                    "ok": r.get("ok", False),
                    "elapsed": r.get("elapsed", 0),
                    "result": r.get("result", "")[:1000],
                    "error": r.get("error", ""),
                    "verdict": r.get("verdict"),
                    "score": r.get("score"),
                }
                for r in result["results"]
            ],
            "elapsed": result["elapsed"],
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "tb": traceback.format_exc()[:500]}
