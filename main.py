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
    query = (body.get("query") or "").strip()[:1000]
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
                on_event("final_verdict", {
                    "verdict": _get(result, "verdict", "unknown"),
                    "score": float(_get(result, "score", 0) or 0),
                    "rounds": _get(result, "rounds", 0) or 0,
                    "elapsed": round(float(_get(result, "elapsed", 0) or 0), 1),
                    "consensus": bool(_get(result, "consensus", False)),
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
    return {
        "status": "ok",
        "bridge": get_council_bridge is not None,
        "topics": search_topics is not None,
        "bridge_error": str(_bridge_err) if _bridge_err else None,
    }


@app.get("/api/history")
async def api_history():
    try:
        from src.council.history import get_history
        return get_history().list_recent(10)
    except Exception as e:
        return {"error": str(e), "items": []}


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
