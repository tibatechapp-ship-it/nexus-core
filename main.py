import asyncio
import hmac
import json
import os
import sys
import time
from pathlib import Path
import threading

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sse_starlette.sse import EventSourceResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ═══ src/ على المسار: طبقة novamind تُستورَد باسم `novamind.*` لا `src.novamind`
# (بدون هذا يعمل الخادم لكن المجلس يرجع صامتاً لوضع offline) ═══
_SRC_DIR = os.path.join(BASE_DIR, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

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

# ═══ Readiness probe (Postgres + Redis) — never raises, see src/readiness.py ═══
try:
    from src import readiness as _readiness
except Exception as e:  # pragma: no cover — defensive only
    _readiness = None
    _readiness_err = e
else:
    _readiness_err = None

_STARTED_AT = time.monotonic()


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


app = FastAPI(title="Nexus Real Workbench", docs_url=None, redoc_url=None)


# ═══ Docs (v1.12.1) — أصول Swagger محلية (بلا CDN) + المواصفة الحيّة ═══
DOCS_DIR = os.path.join(BASE_DIR, "docs")

_VENDOR_MIME = {
    "swagger-ui.css": "text/css; charset=utf-8",
    "swagger-ui-bundle.js": "application/javascript; charset=utf-8",
}


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@app.get("/api/openapi.yaml", include_in_schema=False)
async def openapi_spec():
    p = os.path.join(DOCS_DIR, "openapi.yaml")
    if not os.path.exists(p):
        return JSONResponse({"error": "openapi.yaml missing"}, status_code=404)
    return Response(content=_read_text(p), media_type="application/yaml")


@app.get("/docs", include_in_schema=False)
async def docs_root():
    return RedirectResponse("/docs/swagger")


@app.get("/docs/swagger", response_class=HTMLResponse, include_in_schema=False)
async def docs_swagger():
    p = os.path.join(DOCS_DIR, "swagger.html")
    if not os.path.exists(p):
        return HTMLResponse("<h1>swagger.html missing</h1>", status_code=404)
    return _read_text(p)


@app.get("/docs/vendor/{fname}", include_in_schema=False)
async def docs_vendor(fname: str):
    mt = _VENDOR_MIME.get(fname)
    if not mt:
        return JSONResponse({"error": "not found"}, status_code=404)
    p = os.path.join(DOCS_DIR, "vendor", fname)
    if not os.path.exists(p):
        return JSONResponse({"error": fname + " missing — see docs/api.md"}, status_code=404)
    return Response(content=_read_text(p), media_type=mt)


# ═══ Auth اختياري: فعّله بضبط CRAFT_AUTH_TOKEN (يحمي /api/craft و /api/build) ═══
CRAFT_TOKEN = os.environ.get("CRAFT_AUTH_TOKEN", "").strip()


def _craft_auth(request: Request):
    if not CRAFT_TOKEN:
        return None  # auth معطّل — الوضع المحلي الافتراضي (الخادم على 127.0.0.1)
    tok = request.headers.get("X-Craft-Token", "")
    if tok and hmac.compare_digest(tok, CRAFT_TOKEN):
        return None
    return JSONResponse(
        {"ok": False, "error": "unauthorized: X-Craft-Token required"},
        status_code=401,
    )


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
        "service": "nexus-core",
        "uptime_seconds": round(time.monotonic() - _STARTED_AT, 1),
        "bridge": get_council_bridge is not None,
        "topics": search_topics is not None,
        "builder": Builder is not None,
        "builder_error": str(_builder_err) if _builder_err else None,
        "embeddings": emb_spec,
        "embeddings_requested": emb_env_raw,
        "embeddings_fallback": emb_fallback,
        "bridge_error": str(_bridge_err) if _bridge_err else None,
    }


@app.get("/api/ready")
async def ready():
    """جاهزية: هل Postgres و Redis متاحان فعلاً؟ 200 إذا نعم، 503 إذا لا.

    liveness (`/api/health`) تجيب "العملية حيّة"؛ هذه تجيب "تستطيع خدمة
    الطلبات" — وهو السؤال الذي يقرّره المُنسِّق قبل توجيه الترافيك. الفحص
    يحمل دائماً نفس الشكل (ready/status/checks/version) كي يكون سبب الفشل
    مقروءاً من الاستجابة نفسها دون استدعاء ثانٍ.
    """
    if _readiness is None:  # pragma: no cover — defensive only
        return JSONResponse(
            {"ready": False, "status": "error",
             "error": f"readiness module unavailable: {_readiness_err}"},
            status_code=503,
        )
    payload = await asyncio.to_thread(_readiness.readiness)
    return JSONResponse(payload, status_code=200 if payload.get("ready") else 503)



@app.post("/api/build")
def api_build(request: Request, body: dict):
    """وضع البنّاء: يحوّل قرار المجلس إلى حِزمة ملفات على القرص.

    يقبل ``query`` (يداول ثم يبني) أو ``decision_id`` (يبني من قرار محفوظ).
    """
    _deny = _craft_auth(request)
    if _deny:
        return _deny
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


@app.post("/api/craft")
async def api_craft(request: Request):
    """وضع الصياغة (v1.12): يولّد كوداً فعلياً من وصف حرّ مباشرة.

    يقبل ``query`` (وصف المطلوب)، و``review=true`` لطلب مراجعة الكود المولَّد من
    المجلس نفسه. يعيد ``proof`` يحوي نتيجة ``py_compile`` لكل ملف بايثون.
    """
    _deny = _craft_auth(request)
    if _deny:
        return _deny
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "JSON غير صالح"}
    query = str(body.get("query") or body.get("question") or "").strip()[:800]
    if not query:
        return {"ok": False, "error": "query مطلوب"}
    review = bool(body.get("review"))
    try:
        from src.council.craft import generate_code
        result = await asyncio.to_thread(generate_code, query, review)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@app.get("/api/history")
async def api_history(q: str = "", limit: int = 10):
    """آخر القرارات — أو بحث نصّي عند تمرير ``q`` (v1.11)."""
    try:
        limit = max(1, min(int(limit or 10), 200))
    except (TypeError, ValueError):
        limit = 10
    try:
        from src.council.history import get_history
        h = get_history()
        if (q or "").strip():
            return h.search(q.strip(), limit)
        return h.list_recent(limit)
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


# ═══ PWA assets (v1.11) — تُخدَم من هنا مباشرة، بلا ملفات خارجية ═══
_MANIFEST = {
    "name": "Nexus Council Console",
    "short_name": "Nexus",
    "description": "منصة مداولة الوكلاء الحيّة",
    "lang": "ar",
    "dir": "rtl",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0a0e14",
    "theme_color": "#0a0e14",
    "icons": [
        {"src": "/icon.svg", "sizes": "any",
         "type": "image/svg+xml", "purpose": "any"},
        {"src": "/icon.svg", "sizes": "any",
         "type": "image/svg+xml", "purpose": "maskable"},
    ],
}

_SW_JS = """// Nexus Console service worker (v1.11)
const CACHE = 'nexus-console-v1.11';
const SHELL = ['/', '/icon.svg', '/manifest.json'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;      // لا تخزّن الـ API (SSE حيّ)
  e.respondWith(
    fetch(req).then(res => {
      if (res && res.status === 200 && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req).then(hit => hit || caches.match('/')))
  );
});
"""

_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<rect width="128" height="128" rx="24" fill="#0a0e14"/>
<path d="M64 40 L40 82 M64 40 L88 82 M40 82 L88 82" stroke="#21262d" stroke-width="4"/>
<circle cx="64" cy="40" r="13" fill="#58a6ff"/>
<circle cx="40" cy="82" r="13" fill="#3fb950"/>
<circle cx="88" cy="82" r="13" fill="#d29922"/>
</svg>
"""


@app.get("/manifest.json")
async def pwa_manifest():
    return Response(content=json.dumps(_MANIFEST, ensure_ascii=False),
                    media_type="application/manifest+json")


@app.get("/sw.js")
async def pwa_service_worker():
    return Response(content=_SW_JS, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/"})


@app.get("/icon.svg")
async def pwa_icon():
    return Response(content=_ICON_SVG, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})



# ═══ Review API (v1.12.2) ═══
@app.post("/api/review")
async def api_review(request: Request):
    """مراجعة مشروع محلي عبر المجلس الحي."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON غير صالح"}, status_code=400)

    path_str = (body.get("path") or "").strip()
    max_files = min(int(body.get("max_files", 8)), 20)

    # ═══ أمان: path confinement ═══
    if not path_str or ".." in path_str:
        return JSONResponse({"ok": False, "error": "مسار غير صالح"}, status_code=400)

    p = Path(path_str).expanduser().resolve()
    home = Path.home().resolve()

    if not p.exists():
        return JSONResponse({"ok": False, "error": f"المسار غير موجود: {p}"}, status_code=404)
    if not p.is_dir():
        return JSONResponse({"ok": False, "error": "المسار ليس مجلداً"}, status_code=400)
    # مسارات مسموحة: $HOME و $TMPDIR (Termux)
    import tempfile
    tmp_dir = Path(tempfile.gettempdir()).resolve()
    in_home = (home == p or home in p.parents)
    in_tmp = (tmp_dir == p or tmp_dir in p.parents)
    if not (in_home or in_tmp):
        return JSONResponse({"ok": False, "error": "المسار خارج $HOME/$TMPDIR"}, status_code=403)

    # ═══ جمع الملفات ═══
    ALLOWED = (".py", ".js", ".ts", ".dart", ".java", ".kt", ".go", ".html", ".css", ".md")
    files = []
    total_bytes = 0
    MAX_BYTES = 30_000

    for f in sorted(p.rglob("*")):
        if any(part.startswith(".") for part in f.parts if part != "."):
            continue
        if "node_modules" in f.parts or "__pycache__" in f.parts or "venv" in f.parts:
            continue
        if not f.is_file() or f.suffix not in ALLOWED:
            continue
        try:
            size = f.stat().st_size
            if size > 20_000:
                continue
            file_content = f.read_text(encoding="utf-8")
            total_bytes += size
            rel = f.relative_to(p)
            files.append(f"─── {rel} ({size}B) ───\n{file_content}")
            if len(files) >= max_files or total_bytes > MAX_BYTES:
                break
        except Exception:
            continue

    if not files:
        return JSONResponse({"ok": False, "error": "لا ملفات قابلة للمراجعة"}, status_code=404)

    # ═══ استدعاء المجلس ═══
    if get_council_bridge is None:
        return JSONResponse({"ok": False, "error": f"Bridge غير متوفر: {_bridge_err}"}, status_code=503)

    context = (
        f"راجع كود مشروع «{p.name}» من 4 زوايا: البنية، الأمان، الصيانة، الأداء.\n"
        f"عدد الملفات: {len(files)}\n\n"
        + "\n\n".join(files)
    )

    try:
        result = await asyncio.to_thread(
            lambda: get_council_bridge().deliberate_with_memory(context, use_cache=False)
        )
        return {
            "ok": True,
            "project": p.name,
            "files_reviewed": len(files),
            "bytes_reviewed": total_bytes,
            "verdict": getattr(result, "verdict", None),
            "score": getattr(result, "score", None),
            "recommendation": getattr(result, "recommendation", None),
            "transcript": getattr(result, "transcript", []),
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Review failed: {e}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
