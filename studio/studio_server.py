#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nexus Studio — واجهة تطوير احترافية لمشروع nexus-core
• منفذ مستقل 8001 — لا يلمس الخادم الحي على 8000.
• Fail-closed: توكين إلزامي للربط الخارجي، وإلا loopback فقط.
• safe_path عبر resolve() + relative_to() — تمنع ../ و symlink escape.
• حماية الملفات الحساسة عبر is_sensitive_file الرسمية.
• كتابة ذرّية (tmp + os.replace) وفحص compile() قبل حفظ .py.
• SSE عبر StreamingResponse — بدون اعتماديات إضافية.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

STUDIO_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDIO_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ✅ اجعل LLMRouter يقرأ .env من مجلد المشروع (وليس /public)
# ✅ حمّل .env قبل قراءة أي env var
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env", override=False)
except Exception:
    pass

os.environ.setdefault("NOVAMIND_HOME", str(REPO_ROOT))

from novamind.core.llm_router import LLMRouter  # noqa: E402
from core.backend import OllamaBackend  # noqa: E402
from core.api_backend import APIBackend  # noqa: E402
from core.types import Message  # noqa: E402
import urllib.request  # noqa: E402
import time  # noqa: E402

try:
    from tools.executor import is_sensitive_file  # noqa: E402
except Exception:
    _SENSITIVE = {
        ".env", ".env.local", ".env.production", ".git-credentials",
        "id_rsa", "id_ed25519", "id_ecdsa", "credentials", "credentials.json",
        "secrets.json", "secrets.yaml", "secrets.yml", "service-account.json",
    }
    _SENSITIVE_EXT = {".pem", ".key", ".p12", ".pfx", ".crt"}

    def is_sensitive_file(p: Path) -> bool:  # type: ignore[misc]
        name = p.name.lower()
        if name == ".env.example":
            return False
        if name in _SENSITIVE or name.startswith(".env."):
            return True
        return p.suffix.lower() in _SENSITIVE_EXT


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nexus-studio")

# ═══ Sanitizer — امنع تسرّب المفاتيح في السجلات أو الردود ═══
_SECRET_PATTERNS = [
    (re.compile(r'gsk_[A-Za-z0-9]{40,}'), 'gsk_***REDACTED***'),
    (re.compile(r'sk-[A-Za-z0-9]{40,}'), 'sk-***REDACTED***'),
    (re.compile(r'sk-proj-[A-Za-z0-9_-]{40,}'), 'sk-proj-***REDACTED***'),
    (re.compile(r'AIza[A-Za-z0-9_-]{35}'), 'AIza***REDACTED***'),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), 'ghp_***REDACTED***'),
    (re.compile(r'ghs_[A-Za-z0-9]{36}'), 'ghs_***REDACTED***'),
    (re.compile(r'Bearer\s+[A-Za-z0-9_.\-]{20,}'), 'Bearer ***REDACTED***'),
    (re.compile(r"API_KEY[_0-9]*\s*=\s*[^\s]+"), "API_KEY=***REDACTED***"),
]


def _sanitize(text: str) -> str:
    """يمحو أي مفتاح/توكن محتمل قبل الكتابة في السجل أو إرساله للعميل."""
    s = str(text)
    for pat, repl in _SECRET_PATTERNS:
        s = pat.sub(repl, s)
    return s


BIND = os.environ.get("NEXUS_STUDIO_BIND", "127.0.0.1")
PORT = int(os.environ.get("NEXUS_STUDIO_PORT", "8001"))
TOKEN = os.environ.get("NEXUS_STUDIO_TOKEN", "").strip()
WORKSPACE = Path(os.environ.get("NEXUS_STUDIO_WORKSPACE", str(REPO_ROOT))).resolve()

MAX_READ = 512 * 1024
MAX_WRITE = 1024 * 1024
RUN_TIMEOUT = 10  # seconds
RUN_MAX_OUTPUT = 100_000  # 100KB
MAX_PROMPT = 16 * 1024
MAX_FILES = 4000
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".tox",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
    ".idea", ".vscode", "htmlcov", ".coverage",
}
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}

_LOOP_BINDS = {"127.0.0.1", "localhost", "::1"}
if BIND not in _LOOP_BINDS and not TOKEN:
    raise SystemExit(
        "[studio] رفض الإقلاع (fail-closed): الربط على واجهة خارجية "
        f"({BIND}) يتطلب تعيين NEXUS_STUDIO_TOKEN أولًا."
    )

app = FastAPI(title="Nexus Studio", docs_url=None, redoc_url=None, openapi_url=None)

# ═══ Backend selection: ollama (default) or router (cloud) ═══
STUDIO_BACKEND = os.environ.get("NEXUS_STUDIO_BACKEND", "ollama").lower()
BACKEND = None  # OllamaBackend
ROUTER = None   # LLMRouter

if STUDIO_BACKEND == "ollama":
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            r.read()
        BACKEND = OllamaBackend()
        logger.info("✅ Ollama محلي جاهز — %s", BACKEND.model)
    except Exception as exc:
        logger.error("❌ Ollama غير متاح: %s — العودة إلى LLMRouter", exc)
        STUDIO_BACKEND = "router"

elif STUDIO_BACKEND == "api":
    try:
        _api_url = os.environ.get("NEXUS_STUDIO_API_URL", "").strip()
        _api_keys = os.environ.get("NEXUS_STUDIO_API_KEYS", "").strip()
        _api_model = os.environ.get("NEXUS_STUDIO_MODEL", "").strip() or "qwen-2.5-coder-32b-instruct"
        if not _api_url or not _api_keys:
            raise ValueError("NEXUS_STUDIO_API_URL و NEXUS_STUDIO_API_KEYS مطلوبان")
        BACKEND = APIBackend(base_url=_api_url, api_keys=_api_keys, model=_api_model)
        logger.info("✅ API backend: %s @ %s", BACKEND.model, BACKEND.base_url)
    except Exception as exc:
        logger.error("❌ API backend فشل: %s — العودة إلى LLMRouter", exc)
        STUDIO_BACKEND = "router"

if BACKEND is None:
    try:
        ROUTER = LLMRouter()
        logger.info("LLMRouter سحابي جاهز — %d مزود", len(getattr(ROUTER, "providers", [])))
    except Exception as exc:
        logger.error("فشل تحميل LLMRouter: %s", exc)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _authorized(request: Request) -> bool:
    if TOKEN:
        supplied = request.headers.get("x-studio-token", "").strip()
        if not supplied:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
        return bool(supplied) and hmac.compare_digest(supplied, TOKEN)
    return _client_ip(request) in LOOPBACK


def _require(request: Request) -> None:
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="غير مصرّح")


def safe_path(rel: str) -> Path:
    if not rel or "\x00" in rel:
        raise HTTPException(status_code=400, detail="مسار غير صالح")
    target = (WORKSPACE / rel).resolve()
    try:
        target.relative_to(WORKSPACE)
    except ValueError:
        raise HTTPException(status_code=400, detail="الخروج عن مساحة العمل ممنوع")
    rel_parts = Path(rel).parts
    if any(part in SKIP_DIRS for part in rel_parts):
        raise HTTPException(status_code=403, detail="دليل محمي")
    if is_sensitive_file(target):
        raise HTTPException(status_code=403, detail="ملف حساس — محمي")
    return target


_FENCE = "`" * 3

def extract_code(text: str) -> str:
    m = re.search(_FENCE + r"(?:python|py)?[ \t]*\r?\n(.*?)" + _FENCE, text, re.S)
    return m.group(1).strip() if m else ""


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STUDIO_DIR / "studio.html", media_type="text/html; charset=utf-8")


@app.get("/api/studio/health")
async def health(request: Request) -> JSONResponse:
    _require(request)
    if BACKEND is not None:
        _mode = "api" if isinstance(BACKEND, APIBackend) else "ollama"
        backend_info = {"mode": _mode, "model": BACKEND.model, "providers": 1}
        llm_ready = True
    elif ROUTER is not None:
        backend_info = {"mode": "router", "providers": len(getattr(ROUTER, "providers", []) or [])}
        llm_ready = True
    else:
        backend_info = {"mode": "none", "providers": 0}
        llm_ready = False
    return JSONResponse({
        "ok": True, "version": "1.33.0", "workspace": str(WORKSPACE),
        "auth_mode": "token" if TOKEN else "loopback-only",
        "backend": backend_info,
        "llm_ready": llm_ready,
    })


@app.get("/api/studio/files")
async def list_files(request: Request) -> JSONResponse:
    _require(request)
    out: list[str] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(WORKSPACE):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel_dir = Path(dirpath).relative_to(WORKSPACE)
        for name in sorted(filenames):
            p = rel_dir / name
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".whl", ".ico"}:
                continue
            if is_sensitive_file(WORKSPACE / p):
                continue
            out.append(p.as_posix())
            if len(out) >= MAX_FILES:
                truncated = True
                break
        if truncated:
            break
    return JSONResponse({"files": out, "truncated": truncated})


@app.get("/api/studio/file")
async def read_file(request: Request, path: str) -> JSONResponse:
    _require(request)
    target = safe_path(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    size = target.stat().st_size
    if size > MAX_READ:
        raise HTTPException(status_code=413, detail=f"الملف أكبر من {MAX_READ // 1024}KB")
    return JSONResponse({
        "path": path,
        "content": target.read_text(encoding="utf-8", errors="replace"),
        "size": size,
    })


@app.post("/api/studio/save")
async def save_file(request: Request) -> JSONResponse:
    _require(request)
    body = await request.json()
    rel = str(body.get("path", "")).strip()
    content = body.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content يجب أن يكون نصًا")
    if len(content.encode("utf-8")) > MAX_WRITE:
        raise HTTPException(status_code=413, detail=f"الحجم يتجاوز {MAX_WRITE // 1024}KB")
    if not rel.strip():
        raise HTTPException(status_code=400, detail="حدد مسار الحفظ أولًا")

    target = safe_path(rel)

    if target.suffix == ".py":
        try:
            compile(content, str(target), "exec")
        except SyntaxError as e:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "error": f"خطأ صياغة سطر {e.lineno}: {e.msg}"},
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".studio-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return JSONResponse({"ok": True, "path": rel, "bytes": len(content.encode("utf-8"))})



@app.post("/api/studio/run")
async def run_file(request: Request) -> JSONResponse:
    """تشغيل ملف .py داخل مساحة العمل، مع timeout وحدود أمان."""
    _require(request)
    body = await request.json()
    rel = str(body.get("path", "")).strip()
    if not rel:
        raise HTTPException(status_code=400, detail="حدد مسار الملف أولًا")

    target = safe_path(rel)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    if target.suffix != ".py":
        raise HTTPException(status_code=400, detail="التشغيل متاح فقط لملفات .py")

    # بيئة نظيفة — لا مفاتيح، لا متغيرات سرية
    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(WORKSPACE),
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TERM": "dumb",
    }

    start = time.time()
    try:
        proc = await run_in_threadpool(
            subprocess.run,
            [sys.executable, str(target)],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
            cwd=str(WORKSPACE),
            env=safe_env,
            stdin=subprocess.DEVNULL,
        )
        elapsed = round((time.time() - start) * 1000)
        stdout = proc.stdout[:RUN_MAX_OUTPUT]
        stderr = proc.stderr[:RUN_MAX_OUTPUT]
        return JSONResponse({
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": elapsed,
            "truncated": len(proc.stdout) > RUN_MAX_OUTPUT or len(proc.stderr) > RUN_MAX_OUTPUT,
        })
    except subprocess.TimeoutExpired:
        return JSONResponse({
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"انتهت المهلة ({RUN_TIMEOUT}s) — الكود بطيء أو في حلقة لا نهائية",
            "duration_ms": RUN_TIMEOUT * 1000,
            "truncated": False,
        })
    except Exception as e:
        return JSONResponse({
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"خطأ في التشغيل: {_sanitize(str(e))[:300]}",
            "duration_ms": round((time.time() - start) * 1000),
            "truncated": False,
        })


@app.post("/api/studio/generate")
async def generate(request: Request) -> StreamingResponse:
    _require(request)
    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()[:MAX_PROMPT]
    role = str(body.get("role", "fast")).strip()
    if role not in {"fast", "smart"}:
        role = "fast"
    if not prompt:
        raise HTTPException(status_code=400, detail="اكتب وصف المطلوب أولًا")
    if BACKEND is None and ROUTER is None:
        raise HTTPException(status_code=503, detail="لا backend متاح — شغّل Ollama أو افحص .env")

    async def event_stream() -> AsyncIterator[bytes]:
        def sse(event: str, data: dict) -> bytes:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        yield sse("step", {"msg": "جارٍ تحليل المطلوب وبناء الحل…"})
        system = (
            "أنت كاتب كود Python محترف. اتبع القواعد:\n"
            "1. كود كامل قابل للتشغيل داخل " + _FENCE + "python فقط.\n"
            "2. ابدأ بـ imports اللازمة، ثم عرّف def/class كامل.\n"
            "3. أضف تعليقات عربية موجزة داخل الكود.\n"
            "4. عالج الحالات الحدية (None، فارغ، كبير).\n"
            "5. أضف مثالاً: if __name__ == '__main__': ...\n"
            "6. لا تكتب أي شرح خارج الكتلة.\n"
            "إذا غمض الطلب، اكتب التفسير الأكثر شيوعاً."
        )
        try:
            if BACKEND is not None:
                _msgs = [Message("system", system), Message("user", prompt)]
                _t0 = time.time()
                try:
                    _text = await run_in_threadpool(BACKEND.generate, _msgs)
                    result = {
                        "ok": True, "text": _text,
                        "provider": ("api" if isinstance(BACKEND, APIBackend) else "ollama"), "model": BACKEND.model,
                        "elapsed": round(time.time() - _t0, 2),
                    }
                except Exception as _exc:
                    yield sse("error", {"msg": f"Ollama فشل: {str(_exc)[:200]}"})
                    return
            else:
                result = await run_in_threadpool(
                    ROUTER.generate,
                    prompt=prompt, system=system, role=role,
                    temperature=0.2, allow_fallback=True,
                )
            if not result.get("ok"):
                yield sse("error", {"msg": f"فشل التوليد: {result.get('error', 'لا مزود متاح')}"})
                return

            _prov = result.get("provider", "?")
            _model = result.get("model", "?")
            _elapsed = result.get("elapsed", 0.0)
            yield sse("step", {"msg": f"تم التوليد عبر {_prov} / {_model} خلال {_elapsed} ثانية"})
            yield sse("code", {"text": result.get("text", ""), "provider": _prov, "model": _model})

            code = extract_code(result.get("text", ""))
            if code:
                try:
                    compile(code, "<studio>", "exec")
                    yield sse("test", {"ok": True, "detail": f"الصياغة سليمة ({len(code)} حرفًا)"})
                except SyntaxError as e:
                    yield sse("test", {"ok": False, "detail": f"خطأ صياغة سطر {e.lineno}: {e.msg}"})
            else:
                yield sse("test", {"ok": True, "detail": "لا توجد كتلة Python"})
            yield sse("done", {"ok": True, "provider": _prov})
        except Exception as exc:
            logger.exception("generate failed: %s", _sanitize(str(exc)))
            yield sse("error", {"msg": f"خطأ داخلي: {_sanitize(str(exc))[:300]}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    if isinstance(BACKEND, APIBackend):
        _mode = f"API سحابي ({BACKEND.model})"
    elif isinstance(BACKEND, OllamaBackend):
        _mode = f"Ollama محلي ({BACKEND.model})"
    elif ROUTER is not None:
        _mode = "LLMRouter سحابي"
    else:
        _mode = "بدون backend"
    logger.info("Nexus Studio على http://%s:%d — %s — مساحة العمل: %s", BIND, PORT, _mode, WORKSPACE)
    uvicorn.run(app, host=BIND, port=PORT, log_level="info")
