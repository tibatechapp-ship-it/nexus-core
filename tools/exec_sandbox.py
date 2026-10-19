import ast
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
MAX_CODE_BYTES = 256 * 1024
MAX_OUT_BYTES = 64 * 1024
MAX_FSIZE = 5 * 1024 * 1024
MAX_PROCS = 64
MAX_TIMEOUT = 20
PARALLEL = 2
MEM_LIMITS = {
    "python": 512 * 1024 * 1024,
    "bash": 512 * 1024 * 1024,
    "javascript": 1536 * 1024 * 1024,
}
_sem = threading.BoundedSemaphore(PARALLEL)
LANGS = {
    "python": {"ext": ".py", "cmd": [sys.executable or "python3", "main.py"]},
    "javascript": {"ext": ".js", "cmd": ["node", "main.js"]},
    "bash": {"ext": ".sh", "cmd": ["bash", "main.sh"]},
}
ALIASES = {
    "py": "python",
    "js": "javascript",
    "node": "javascript",
    "sh": "bash",
    "shell": "bash",
}
WARNINGS = {
    "python": [
        ("network", r"\b(requests|urllib|socket|httpx)\b"),
        ("system", r"\b(os\.system|subprocess)\b"),
        ("eval", r"\b(eval|exec)\s*\("),
        ("delete", r"\b(shutil\.rmtree|os\.remove|os\.unlink)\b"),
    ],
    "javascript": [("eval", r"\beval\s*\("), ("child_process", r"child_process")],
    "bash": [
        ("rm-rf", r"rm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+[~/]"),
        ("curl|sh", r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b"),
    ],
}


class ExecReq(BaseModel):
    language: str
    code: str
    stdin: str = ""
    timeout: int = 10


def _is_termux():
    return "com.termux" in os.environ.get("PREFIX", "") or os.path.exists(
        "/data/data/com.termux"
    )


def _make_limits(mem):
    def _apply():
        def setlim(res, val):
            try:
                resource.setrlimit(res, (val, val))
            except Exception:
                pass

        setlim(resource.RLIMIT_CPU, MAX_TIMEOUT)
        setlim(resource.RLIMIT_FSIZE, MAX_FSIZE)
        # ⚠️ RLIMIT_AS محذوف على Termux:
        #    Android kernel يرسل SIGABRT (exit_code=-6) عند أي حد ذاكرة
        #    لأن Python 3.14 يحجز address space كبيراً عند البدء.
        #    الحماية تبقى عبر: RLIMIT_CPU + MAX_TIMEOUT + killpg + MAX_OUT_BYTES
        if not _is_termux():
            setlim(resource.RLIMIT_AS, mem)
            try:
                cur, _ = resource.getrlimit(resource.RLIMIT_NPROC)
                if cur != -1 and cur < 1000:
                    resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCS, MAX_PROCS))
            except Exception:
                pass

    return _apply


def _env(wd):
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": wd,
        "TMPDIR": wd,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def _read_cap(path, cap=MAX_OUT_BYTES):
    try:
        with open(path, "rb") as fh:
            data = fh.read(cap + 1)
        return data[:cap].decode("utf-8", "replace"), len(data) > cap
    except Exception:
        return "", False


def _scan_warnings(lang, code):
    return [label for label, pat in WARNINGS.get(lang, []) if re.search(pat, code)]


@router.get("/api/exec/tools")
def exec_tools():
    node_v = None
    if shutil.which("node"):
        try:
            node_v = (
                subprocess.run(
                    ["node", "--version"], capture_output=True, timeout=5
                )
                .stdout.decode()
                .strip()[:20]
                or None
            )
        except Exception:
            node_v = None
    return {
        "runtimes": {
            "python": ".".join(map(str, sys.version_info[:3])),
            "javascript": node_v,
            "bash": "متوفر" if shutil.which("bash") else None,
        },
        "max_timeout": MAX_TIMEOUT,
        "parallel": PARALLEL,
        "caps": {"code_kb": MAX_CODE_BYTES // 1024, "output_kb": MAX_OUT_BYTES // 1024},
        "env": "termux" if _is_termux() else "linux",
    }


@router.post("/api/exec")
def exec_code(req: ExecReq):
    lang = ALIASES.get(req.language.lower().strip(), req.language.lower().strip())
    if lang not in LANGS:
        raise HTTPException(400, detail="لغة غير مدعومة: " + req.language)
    if len(req.code.encode("utf-8")) > MAX_CODE_BYTES:
        raise HTTPException(413, detail="الكود أكبر من %dKB" % (MAX_CODE_BYTES // 1024))
    if lang == "javascript" and not shutil.which("node"):
        raise HTTPException(400, detail="node غير مثبت")
    t = max(1, min(req.timeout or 10, MAX_TIMEOUT))
    if not _sem.acquire(blocking=False):
        raise HTTPException(429, detail="بيئة التنفيذ مشغولة")
    t0 = time.monotonic()
    try:
        return _run(lang, LANGS[lang], req, t, t0)
    finally:
        _sem.release()


def _run(lang, spec, req, t, t0):
    with tempfile.TemporaryDirectory(prefix="nx_exec_") as wd:
        src = os.path.join(wd, "main" + spec["ext"])
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(req.code)
        if lang == "python":
            try:
                ast.parse(req.code)
                verified, verr = True, ""
            except SyntaxError as e:
                verified, verr = False, "SyntaxError (سطر %s): %s" % (e.lineno, e.msg)
        else:
            chk = (
                ["node", "--check", "main.js"]
                if lang == "javascript"
                else ["bash", "-n", "main.sh"]
            )
            try:
                p = subprocess.run(chk, cwd=wd, capture_output=True, timeout=8, env=_env(wd))
                verified = p.returncode == 0
                verr = ((p.stderr or p.stdout or b"").decode("utf-8", "replace"))[
                    :2000
                ].strip()
            except Exception as e:
                verified, verr = False, "تعذر الفحص: %s" % e
        base = {
            "language": lang,
            "verified": verified,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "warnings": _scan_warnings(lang, req.code),
        }
        if not verified:
            return {
                **base,
                "ran": False,
                "exit_code": None,
                "timed_out": False,
                "stdout": "",
                "stderr": "",
                "truncated": False,
                "verify_error": verr,
            }
        outf = os.path.join(wd, "out.log")
        errf = os.path.join(wd, "err.log")
        preexec = _make_limits(MEM_LIMITS[lang]) if os.name == "posix" else None
        with open(outf, "wb") as fo, open(errf, "wb") as fe:
            proc = subprocess.Popen(
                spec["cmd"],
                cwd=wd,
                env=_env(wd),
                stdin=subprocess.PIPE if req.stdin else subprocess.DEVNULL,
                stdout=fo,
                stderr=fe,
                start_new_session=True,
                preexec_fn=preexec,
            )
            timed_out = False
            try:
                proc.communicate(
                    input=req.stdin.encode("utf-8") if req.stdin else None, timeout=t
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.communicate(timeout=5)
                except Exception:
                    pass
        out, tr_o = _read_cap(outf)
        err, tr_e = _read_cap(errf)
        return {
            **base,
            "ran": True,
            "exit_code": proc.returncode,
            "timed_out": timed_out,
            "stdout": out,
            "stderr": err,
            "truncated": tr_o or tr_e,
            "verify_error": "",
        }
