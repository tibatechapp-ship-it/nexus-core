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
from pathlib import Path

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
    """Resolve a plan path inside workdir; refuse absolute or escaping paths."""
    target = (workdir / rel).resolve()
    if not str(target).startswith(str(workdir.resolve())):
        raise ValueError(f"path escapes sandbox: {rel!r}")
    return target


def apply_plan(plan: RepairPlan, workdir: Path) -> dict:
    """Apply every step's file mutation inside ``workdir`` only."""
    applied, errors = [], []
    for step in plan.steps:
        try:
            target = _safe_target(workdir, step.file)
            if step.action == "delete":
                if target.exists():
                    target.unlink()
            else:
                content = step.patch_hint
                if step.action == "edit" and target.exists():
                    existing = target.read_text(encoding="utf-8", errors="replace")
                    sep = "" if existing.endswith("\n") else "\n"
                    content = existing + sep + content
                if len(content.encode()) > MAX_FILE_BYTES:
                    raise ValueError("file exceeds sandbox size cap")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            applied.append({"file": step.file, "action": step.action, "ok": True})
        except (ValueError, OSError) as exc:
            errors.append({"file": step.file, "action": step.action, "error": str(exc)[:200]})
    return {"ok": not errors, "applied": applied, "errors": errors}


def run_cmd(cmd: list, workdir: Path, timeout: int = MAX_TIMEOUT_S) -> dict:
    """Run one command in a sandboxed subprocess (rlimits, fresh session)."""
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
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            return {"ok": False, "exit_code": None, "timeout": True,
                    "stdout": "", "stderr": "sandbox timeout"}

        def capped(data: bytes) -> str:
            return data.decode("utf-8", "replace")[:MAX_OUTPUT_BYTES]

        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "timeout": False,
                "stdout": capped(out), "stderr": capped(err)}
    except OSError as exc:
        return {"ok": False, "exit_code": None, "timeout": False,
                "stdout": "", "stderr": f"spawn failed: {exc}"[:200]}


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
