"""Nexus-Core Web Dashboard."""
from __future__ import annotations
import sys
import threading
import time
import html as _html
import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _setup_mock() -> None:
    from novamind.core.llm_router import LLMRouter
    def mock_gen(self, prompt: str = "", system: str = "", **kw: Any) -> dict[str, Any]:
        s = str(system)
        p = str(prompt)
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
_status_cache: dict[str, Any] = {"data": None, "ts": 0}

# ═══ تتبع المهام الجارية (قراءة-فقت للوحة) ═══
_runs_lock = threading.Lock()
_runs: set[str] = set()
_run_seq = itertools.count(1)


def _run_started() -> str:
    """سجّل بدء مهمة — يُستدعى من المسارات الثقيلة فقط."""
    with _runs_lock:
        rid = f"run-{next(_run_seq)}"
        _runs.add(rid)
        return rid


def _run_finished(rid: str) -> None:
    with _runs_lock:
        _runs.discard(rid)


def _tasks_running() -> int:
    with _runs_lock:
        return len(_runs)

@app.get("/api/status")
def status() -> dict:
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
def list_agents() -> dict:
    from nova.registry import REGISTRY, agents_by_category
    r = {}
    for cat in ['code','security','quality','infra','data','ui','research','meta']:
        r[cat] = agents_by_category(cat)
    return {"total": len(REGISTRY), "by_category": r}


@app.post("/api/agent/run")
def run_agent(req: AgentRunRequest) -> dict:
    _rid = _run_started()
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
                if enriched != prompt:
                    prompt = enriched
            except Exception:
                pass
        start = time.time()
        result = getattr(agent, method)(prompt)
        return {"ok": True, "agent": req.agent, "method": method,
                "result": str(result)[:3000], "elapsed": time.time() - start}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        _run_finished(_rid)


@app.post("/api/rag/add")
def rag_add(req: RAGAddRequest) -> dict:
    from src.memory.agent_rag_bridge import get_bridge
    b = get_bridge()
    return {"ok": True, "doc_id": b.remember(req.text)}


@app.get("/api/rag/query")
def rag_query(q: str, k: int = 5) -> dict:
    from src.memory.agent_rag_bridge import get_bridge
    b = get_bridge()
    results = b.recall(q, k=k)
    return {"ok": True, "query": q,
            "results": [{"id": r.id, "text": r.text, "distance": r.distance} for r in results]}


@app.post("/api/council/deliberate")
def council_deliberate(req: CouncilRequest) -> dict:
    _rid = _run_started()
    try:
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
    finally:
        _run_finished(_rid)


# ═══ Topics ═══
@app.get("/api/council/topics")
def list_topics() -> dict:
    try:
        from src.council.topics import list_categories
        return {"ok": True, "categories": list_categories()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/council/topic")
def run_topic(req: CouncilRequest) -> dict:
    _rid = _run_started()
    try:
        from src.council.topics import get_topic
        t = get_topic(req.question)  # نستخدم حقل question كـ topic_id
        if not t:
            return {"ok": False, "error": "topic not found"}
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
    finally:
        _run_finished(_rid)


@app.get("/api/council/history")
def council_history() -> dict:
    try:
        from src.council.history import get_history
        h = get_history()
        return {"ok": True, "stats": h.stats(), "recent": h.list_recent(10)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══ Cache ═══
@app.get("/api/cache/stats")
def cache_stats() -> dict:
    try:
        from src.council.cache import get_cache
        return {"ok": True, "stats": get_cache().stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/cache/clear")
def cache_clear() -> dict:
    try:
        from src.council.cache import get_cache
        count = get_cache().clear()
        return {"ok": True, "cleared": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══ Metrics ═══
@app.get("/api/metrics/today")
def metrics_today() -> dict:
    try:
        from src.nexus.monitoring import get_monitor
        return {"ok": True, "stats": get_monitor().get_today_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/metrics/clear")
def metrics_clear() -> dict:
    try:
        from src.nexus.monitoring import get_monitor
        count = get_monitor().clear_today()
        return {"ok": True, "cleared": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}




# ═══ Hybrid Router Endpoint ═══
class HybridRequest(BaseModel):
    prompt: str
    force: str | None = None


@app.post("/api/hybrid/run")
def hybrid_run(req: HybridRequest) -> dict:
    """يستخدم Hybrid Router (code/tool/decision)."""
    _rid = _run_started()
    try:
        from src.orchestrator.hybrid_router import HybridRouter, classify

        route = req.force or classify(req.prompt)
        router = HybridRouter(use_rag=True, verbose=False)
        result = router.run(req.prompt, force=req.force)

        return {
            "ok": result.get("ok", False),
            "route": route,
            "method": result.get("method", "?"),
            "elapsed": result.get("total_elapsed", 0),
            "answer": result.get("answer", "")[:2000],
            "iterations": result.get("iterations", 0),
            "trace": [
                {"icon": t.get("icon"), "text": t.get("text", "")[:200]}
                for t in result.get("trace", [])
            ],
            "verdict": result.get("verdict"),
            "score": result.get("score"),
            "transcript": result.get("transcript", []),
            "agents": [r.get("agent") for r in result.get("results", [])],
        }
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "tb": traceback.format_exc()[:500]}
    finally:
        _run_finished(_rid)


DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return DASHBOARD


# ═══ Smart Router Endpoint ═══
class SmartRequest(BaseModel):
    prompt: str
    force_strategy: str | None = None


@app.post("/api/smart/run")
def smart_run(req: SmartRequest) -> dict:
    """يستخدم Smart Router لاختيار الاستراتيجية المثلى."""
    _rid = _run_started()
    try:
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
    finally:
        _run_finished(_rid)


# ═══ لوحة القراءة-فقط (Week-1: الوكلاء النشطون، المهام الجارية، آخر القرارات) ═══

DASHBOARD_CATEGORIES = ('code', 'security', 'quality', 'infra',
                        'data', 'ui', 'research', 'meta')


def _dashboard_summary() -> dict[str, Any]:
    """تجميع قراءة-فقط: لا ينفّذ شيئاً — يجمع حالة الوكلاء والمهام والقرارات."""
    out: dict[str, Any] = {"ok": True}
    try:
        from nova.registry import REGISTRY, agents_by_category
        out["agents"] = {
            "total": len(REGISTRY),
            "by_category": {c: agents_by_category(c)
                            for c in DASHBOARD_CATEGORIES},
        }
    except Exception as e:
        out["agents"] = {"total": 0, "by_category": {}, "error": str(e)}
    out["tasks_running"] = _tasks_running()
    try:
        from src.council.history import get_history
        out["recent_decisions"] = list(get_history().list_recent(5))
    except Exception as e:
        out["recent_decisions"] = []
        out["decisions_error"] = str(e)
    out["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


@app.get("/api/dashboard")
def dashboard_summary_api() -> dict:
    """ملخص قراءة-فقت للوحة — بلا تنفيذ ولا آثار جانبية."""
    return _dashboard_summary()


_DASHBOARD_PAGE = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexus-Core — لوحة القراءة-فقط</title>
<style>
body{font-family:system-ui,'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;
     max-width:820px;margin:2rem auto;padding:0 1rem;line-height:1.7}
h1{font-size:1.4rem;border-bottom:1px solid #30363d;padding-bottom:.5rem}
section{background:#161b22;border:1px solid #30363d;border-radius:8px;
        padding:1rem 1.25rem;margin:1rem 0}
.num{font-size:2rem;font-weight:700;color:#58a6ff;margin:0}
ul{padding-right:1.2rem;margin:.3rem 0}
.muted{color:#8b949e;font-size:.85rem}
a{color:#58a6ff;text-decoration:none}
li{margin:.25rem 0}
</style>
</head>
<body>
<h1>🧠 Nexus-Core — لوحة القراءة-فقط</h1>
<p class="muted">لحظة التوليد: __GENERATED_AT__ · <a href="/">الواجهة التفاعلية الكاملة</a></p>
<section>
  <h2>الوكلاء النشطون</h2>
  <p class="num">__AGENTS_TOTAL__</p>
  <ul>__CATEGORY_ITEMS__</ul>
</section>
<section>
  <h2>المهام الجارية الآن</h2>
  <p class="num">__TASKS_RUNNING__</p>
</section>
<section>
  <h2>آخر القرارات (المجلس)</h2>
  __DECISIONS_BLOCK__
</section>
</body>
</html>
"""


def _decisions_html(items: list[Any], error: str | None) -> str:
    if error:
        return f'<p class="muted">سجل القرارات غير متاح: {_html.escape(error)}</p>'
    if not items:
        return '<p class="muted">لا قرارات مسجلة بعد.</p>'
    lis = []
    for it in items:
        if isinstance(it, dict):
            title = it.get("question") or it.get("title") or it.get("id") or "قرار"
            verdict = it.get("verdict")
            suffix = f" — {verdict}" if verdict else ""
        else:
            title, suffix = str(it), ""
        lis.append(f'<li>{_html.escape(str(title))[:120]}'
                   f'{_html.escape(suffix)}</li>')
    return "<ul>" + "".join(lis) + "</ul>"


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    """صفحة قراءة-فقت خفيفة: حالة لحظية بلا أزرار تنفيذ."""
    s = _dashboard_summary()
    cats = s["agents"].get("by_category", {})
    items = "".join(
        f"<li>{_html.escape(str(c))}: {len(v)}</li>"
        if isinstance(v, list) else
        f"<li>{_html.escape(str(c))}: {_html.escape(str(v))}</li>"
        for c, v in cats.items()
    )
    page = _DASHBOARD_PAGE
    for key, val in (
        ("__GENERATED_AT__", _html.escape(str(s["generated_at"]))),
        ("__AGENTS_TOTAL__", str(s["agents"].get("total", 0))),
        ("__CATEGORY_ITEMS__", items),
        ("__TASKS_RUNNING__", str(s["tasks_running"])),
        ("__DECISIONS_BLOCK__", _decisions_html(
            s["recent_decisions"], s.get("decisions_error"))),
    ):
        page = page.replace(key, val)
    return page
