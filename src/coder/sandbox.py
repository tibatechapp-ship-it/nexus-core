"""Isolated execution — stage 4: mutations stay inside a workdir, verification
runs in an rlimits-boxed subprocess.

الصندوق المعزول (مهمة M2.4): تعديلات الملفات لا تلمس شيئًا خارج مجلد العمل،
والتحقق يجري بعملية منفصلة بحدود موارد مستعارة من نمط hyper_agent (بلا
RLIMIT_AS عمدًا — راجع BUG-6 في توثيق المنصة).
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.coder.plan import RepairPlan

MAX_TIMEOUT_S = 120
MAX_OUTPUT_BYTES = 64 * 1024
MAX_FILE_BYTES = 256 * 1024


def _make_limits() -> None:
    """Termux-safe resource caps (CPU 60s, files 5MiB, 64 procs) — no RLIMIT_AS."""
    for res, limit in (
        (resource.RLIMIT_CPU, 60),
        (resource.RLIMIT_FSIZE, 5 * 1024 * 1024),
        (resource.RLIMIT_NPROC, 64),
    ):
        try:
            resource.setrlimit(res, (limit, limit))
        except (ValueError, OSError):  # platform may refuse some limits
            pass


def new_workdir(base: Path | None = None) -> Path:
    """Create a fresh isolated workspace (never the real repo)."""
    return Path(tempfile.mkdtemp(prefix="coder-sandbox-", dir=str(base) if base else None))


def _safe_target(workdir: Path, rel: str) -> Path:
    """Resolve a plan path inside workdir; refuse absolute or escaping paths.

    ض4 (v1.58.0): path comparison (``is_relative_to``) replaces the old
    textual ``startswith`` check — a sibling directory whose name *begins*
    with the workdir's name (``/tmp/work-other`` vs ``/tmp/work``) no longer
    slips through.
    """
    root = workdir.resolve()
    target = (workdir / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes sandbox: {rel!r}")
    return target


def _size_guard(content: str) -> None:
    """Raise when the produced content would exceed the sandbox file cap."""
    if len(content.encode()) > MAX_FILE_BYTES:
        raise ValueError("file exceeds sandbox size cap")


def apply_plan(plan: RepairPlan, workdir: Path) -> dict:
    """Apply every step's file mutation inside ``workdir`` only.

    ض6 (v1.58.0) — explicit mutation semantics (no implicit writes):
    * ``create`` refuses to overwrite an existing file — unintended
      replacement was silently accepted before.
    * ``edit`` replaces a **unique** block: ``step.find`` must occur exactly
      once in the file and is replaced by ``patch_hint``. The old behavior
      blindly appended the hint to the end of the file, which is not an edit.
    * any unknown action is recorded as an error (it used to fall through to
      a full-file write).
    """
    applied, errors = [], []
    for step in plan.steps:
        try:
            target = _safe_target(workdir, step.file)
            if step.action == "delete":
                if target.exists():
                    target.unlink()
            elif step.action == "create":
                if target.exists():
                    raise ValueError(
                        f"refusing to overwrite existing file: {step.file!r}"
                    )
                _size_guard(step.patch_hint)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(step.patch_hint, encoding="utf-8")
            elif step.action == "edit":
                if not target.exists():
                    raise FileNotFoundError(f"edit target missing: {step.file!r}")
                if not step.find:
                    raise ValueError("edit requires a unique 'find' block")
                existing = target.read_text(encoding="utf-8", errors="replace")
                count = existing.count(step.find)
                if count != 1:
                    raise ValueError(
                        f"'find' block matched {count} times (need exactly 1)"
                    )
                content = existing.replace(step.find, step.patch_hint)
                _size_guard(content)
                target.write_text(content, encoding="utf-8")
            else:
                raise ValueError(f"unknown action: {step.action!r}")
            applied.append({"file": step.file, "action": step.action, "ok": True})
        except (ValueError, OSError) as exc:
            errors.append({"file": step.file, "action": step.action, "error": str(exc)[:200]})
    return {"ok": not errors, "applied": applied, "errors": errors}


def _kill_group(proc: subprocess.Popen) -> None:
    """ض5: kill the WHOLE process group (``start_new_session`` made ``proc``
    the session leader), not just the direct child — grandchildren otherwise
    survive the timeout and keep the pipes open."""
    try:
        if os.name == "posix":
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover - platform split
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:  # the leader may already be gone — take it down anyway
            proc.kill()
        except OSError:
            pass


def run_cmd(cmd: list, workdir: Path, timeout: int = MAX_TIMEOUT_S) -> dict:
    """Run one command in a sandboxed subprocess (rlimits, fresh session).

    ض5 (v1.58.0): output is bounded **while reading** — two drain threads stop
    accumulating past :data:`MAX_OUTPUT_BYTES` (excess is discarded, the child
    is never blocked by a full pipe), so a chatty process can no longer
    balloon memory before the post-hoc truncation. On timeout the entire
    session's process group is killed.
    """
    timeout = min(max(int(timeout), 1), MAX_TIMEOUT_S)
    env = {"HOME": str(workdir), "TMPDIR": str(workdir), "PATH": os.environ.get("PATH", "/usr/bin"),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
    preexec = _make_limits if os.name == "posix" else None  # pragma: no cover - platform split
    try:
        proc = subprocess.Popen(  # noqa: S603 — argv list, no shell
            [str(c) for c in cmd],
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=preexec,
        )
    except OSError as exc:
        return {"ok": False, "exit_code": None, "timeout": False,
                "stdout": "", "stderr": f"spawn failed: {exc}"[:200]}

    out_buf, err_buf = bytearray(), bytearray()
    truncated = False

    def _drain(pipe: Any, sink: bytearray) -> None:
        nonlocal truncated
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                if len(sink) < MAX_OUTPUT_BYTES:
                    sink.extend(chunk[: MAX_OUTPUT_BYTES - len(sink)])
                else:
                    truncated = True  # keep draining, discard the excess
        except (OSError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=_drain, args=(proc.stdout, out_buf), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_buf), daemon=True),
    ]
    for t in threads:
        t.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        proc.wait()
    for t in threads:
        t.join(timeout=5)

    if timed_out:
        return {"ok": False, "exit_code": None, "timeout": True,
                "stdout": out_buf.decode("utf-8", "replace"),
                "stderr": "sandbox timeout",
                "truncated": truncated}

    def capped(data: bytearray) -> str:
        return data.decode("utf-8", "replace")[:MAX_OUTPUT_BYTES]

    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "timeout": False,
            "stdout": capped(out_buf), "stderr": capped(err_buf),
            "truncated": truncated}


def run_tests(test_paths: list, workdir: Path, timeout: int = MAX_TIMEOUT_S) -> dict:
    """Run the plan's declared tests inside the sandbox; verdict comes from rc."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", *test_paths]
    res = run_cmd(cmd, workdir, timeout=timeout)
    res["tests"] = test_paths
    return res


def export_record(plan: RepairPlan, workdir: Path, outcome: dict) -> str:
    """One replayable JSONL line: plan + per-step results + test verdict."""
    return json.dumps(
        {"plan": plan.to_json(), "workdir": str(workdir), "outcome": outcome},
        ensure_ascii=False,
    )


def cleanup(workdir: Path) -> None:
    """Best-effort workspace removal (sandbox hygiene)."""
    shutil.rmtree(workdir, ignore_errors=True)
