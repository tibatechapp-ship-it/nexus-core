import os, sys, json, threading, asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ═══ اضبط NOVAMIND_HOME قبل أي استيراد ═══
os.environ["NOVAMIND_HOME"] = BASE_DIR

# ═══ حمّل .env أولاً ═══
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    pass

try:
    from src.council.rag_bridge import get_council_bridge
    _bridge_err = None
except Exception as e:
    get_council_bridge, _bridge_err = None, e

try:
    from src.council.topics import search_topics, get_topic
except Exception:
    search_topics = get_topic = None

try:
    from src.council.recommend import extract_recommendation
except Exception:
    extract_recommendation = None

# ═══ Builder mode (v2.0) ═══
try:
    from src.council.builder import Builder, list_builds, get_build
    _builder_err = None
except Exception as e:
    Builder = list_builds = get_build = None
    _builder_err = e

try:
    from src.memory.embedding_config import ENV_VAR as _EMB_ENV, resolve_rag as _resolve_rag
    _emb_err = None
except Exception as e:
    _EMB_ENV = _resolve_rag = None
    _emb_err = e


def _embeddings_info():
    """(المزود الفعلي, سبب الرجوع) — لا يرفع استثناءً أبداً."""
    if _resolve_rag is None:
        return None, str(_emb_err) if _emb_err else "unavailable"
    try:
        r = _resolve_rag()
        return r.spec, r.fallback_reason
    except Exception as exc:  # احتياط أخير
        return None, f"{type(exc).__name__}: {exc}"

def _app_version():
    """إصدار التطبيق من مصدر واحد (pyproject.toml) — لا تكرار يدوي."""
    try:
        import tomllib
        with open(os.path.join(BASE_DIR, "pyproject.toml"), "rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        return "unknown"


app = FastAPI(title="Nexus Real Workbench")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()


def _get(obj, name, default=None):
    v = getattr(obj, name, None)
    if v is None and isinstance(obj, dict):
        v = obj.get(name)
    return v if v is not None else default


@app.post("/api/deliberate")
async def deliberate_stream(request: Request):
    body = await request.json()
    query = ((body.get("query") or body.get("question") or "")).strip()[:1000]
    if not query:
        return {"error": "الاستعلام فارغ"}

    async def event_generator():
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        DONE = object()

        def on_event(event, payload):
            try:
                data = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                data = json.dumps({"message": str(payload)}, ensure_ascii=False)
            loop.call_soon_threadsafe(q.put_nowait, {"event": event, "data": data})

        # 1) init + context (سريع)
        yield {"event": "status", "data": json.dumps(
            {"phase": "init", "message": "جاري تحليل الاستعلام..."}, ensure_ascii=False)}
        try:
            if search_topics and get_topic:
                matches = search_topics(query)
                if matches:
                    topic = get_topic(matches[0]["id"])
                    yield {"event": "status", "data": json.dumps(
                        {"phase": "context", "message": "سياق مرتبط: " + topic.title,
                         "topic_id": topic.id}, ensure_ascii=False)}
        except Exception:
            pass

        # 2) المداولة في Thread
        def run():
            try:
                if get_council_bridge is None:
                    on_event("error", {"message": "Bridge غير متوفر: " + str(_bridge_err)})
                    return
                bridge = get_council_bridge()
                on_event("status", {"phase": "council_start", "message": "بدء المداولة الحية..."})
                result = bridge.deliberate_streaming(query, on_event)
                if extract_recommendation is not None:
                    recommendation = extract_recommendation(_get(result, "transcript", []))
                else:
                    recommendation = ""
                on_event("final_verdict", {
                    "verdict": _get(result, "verdict", "unknown"),
                    "score": float(_get(result, "score", 0) or 0),
                    "rounds": _get(result, "rounds", 0) or 0,
                    "elapsed": round(float(_get(result, "elapsed", 0) or 0), 1),
                    "consensus": bool(_get(result, "consensus", False)),
                    "recommendation": recommendation,
                    "record_id": _get(result, "_record_id", "") or "",
                })
            except Exception as e:
                on_event("error", {"message": type(e).__name__ + ": " + str(e)})
            finally:
                loop.call_soon_threadsafe(q.put_nowait, DONE)

        threading.Thread(target=run, daemon=True).start()

        # 3) المضخة
        try:
            while True:
                ev = await q.get()
                if ev is DONE:
                    break
                yield ev
        except asyncio.CancelledError:
            raise

    return EventSourceResponse(event_generator())


@app.get("/api/health")
async def health():
    emb_spec, emb_fallback = _embeddings_info()
    emb_env_raw = (os.environ.get(_EMB_ENV) if _EMB_ENV else None) or None
    return {
        "version": _app_version(),
        "status": "ok",
        "bridge": get_council_bridge is not None,
        "topics": search_topics is not None,
        "builder": Builder is not None,
        "builder_error": str(_builder_err) if _builder_err else None,
        "embeddings": emb_spec,
        "embeddings_requested": emb_env_raw,
        "embeddings_fallback": emb_fallback,
        "bridge_error": str(_bridge_err) if _bridge_err else None,
    }


@app.post("/api/build")
def api_build(body: dict):
    """وضع البنّاء: يحوّل قرار المجلس إلى حِزمة ملفات على القرص.

    يقبل ``query`` (يداول ثم يبني) أو ``decision_id`` (يبني من قرار محفوظ).
    """
    if Builder is None:
        return {"ok": False, "error": "Builder غير متوفر: " + str(_builder_err)}

    query = str(body.get("query") or "").strip()[:1000]
    decision_id = str(body.get("decision_id") or "").strip()
    use_llm = bool(body.get("use_llm", True))

    result = None
    if decision_id:
        try:
            from src.council.history import get_history
            result = get_history().get_full(decision_id)
        except Exception:
            result = None
        if not result:
            return {"ok": False, "error": "قرار غير موجود: " + decision_id}
        query = query or str(result.get("query", ""))
    elif query:
        if get_council_bridge is None:
            return {"ok": False, "error": "Bridge غير متوفر: " + str(_bridge_err)}
        result = get_council_bridge().deliberate_with_memory(query, use_cache=True)
    else:
        return {"ok": False, "error": "أدخل query أو decision_id"}

    llm = None
    if get_council_bridge is not None:
        try:
            llm = get_council_bridge().engine.llm
        except Exception:
            llm = None

    out = Builder(llm=llm).build(query, result, use_llm=use_llm and llm is not None)
    return {
        "ok": out.ok,
        "build_id": out.build_id,
        "title": out.title,
        "kind": out.kind,
        "summary": out.summary,
        "dir": out.dir,
        "files": [{"path": f.path, "bytes": len(f.content.encode("utf-8"))}
                  for f in out.files],
        "proof": out.proof,
    }


@app.get("/api/builds")
def api_builds(n: int = 20):
    if list_builds is None:
        return {"error": "Builder غير متوفر", "items": []}
    return {"items": list_builds(n=n)}


@app.get("/api/builds/{build_id}")
def api_build_detail(build_id: str):
    if get_build is None:
        return {"error": "Builder غير متوفر"}
    return get_build(build_id) or {"error": "not found"}


@app.get("/api/history")
async def api_history():
    try:
        from src.council.history import get_history
        return get_history().list_recent(10)
    except Exception as e:
        return {"error": str(e), "items": []}


@app.get("/api/history/{rec_id}")
async def api_history_detail(rec_id: str):
    try:
        from src.council.history import get_history
        return get_history().get_full(rec_id) or {"error": "not found"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/topics")
async def api_topics():
    try:
        from src.council.topics import TOPICS
        return [{"id": tid, "title": t.title, "category": t.category,
                 "question": t.question, "risk": t.risk_level}
                for tid, t in TOPICS.items()]
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/stats")
async def api_stats():
    try:
        from src.council.history import get_history
        return get_history().stats()
    except Exception as e:
        return {"total": 0, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
