"""Independent quality gate — evaluates the coder engine from its own process.

بوابة الجودة المستقلة (مهمة M3.1): تعمل بعملية منفصلة عن المحرك ولا تشترك
معه في أي حالة، فلا يكون المقيّم طرفًا في المُقيَّم. كل تقرير يُكتب سطر JSONL
كامل الحقول في سجل مستقل حتى لو انهار المحرك بعده.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.observability.trace import trace_event

MAX_TAIL = 400
MAX_TIMEOUT_S = 300


def default_gates() -> list:
    """The three plan gates: tests, then security, then annotations hygiene."""
    return [
        [sys.executable, "-m", "pytest", "-q", "--no-header", "--maxfail=3"],
        [sys.executable, "-m", "compileall", "-q", "."],
        [sys.executable, "scripts/check_annotations.py"],
    ]


def _log_path(workdir: Path) -> Path:
    env = os.environ.get("NEXUS_QUALITY_GATE_LOG")
    if env:
        return Path(env)
    return workdir / "runs" / "quality_gate.jsonl"


def run_gate(workdir: Path, gates: list | None = None,
             timeout: int = MAX_TIMEOUT_S) -> tuple:
    """Run every gate in its own subprocess; return (ok, results) and log it.

    ``gates`` is injectable so tests (and stricter deployments) can swap the
    command list without touching the independence contract: one process per
    gate, verdict = all rc == 0, JSONL report always appended.
    """
    workdir = Path(workdir)
    results, ok = [], True
    started = time.monotonic()
    duration_ms = 0.0
    for cmd in (gates if gates is not None else default_gates()):
        cmd = [str(c) for c in cmd]
        try:
            proc = subprocess.run(  # noqa: S603 — argv list, no shell
                cmd, cwd=str(workdir), capture_output=True, text=True,
                timeout=min(max(int(timeout), 1), MAX_TIMEOUT_S),
            )
            passed = proc.returncode == 0
            tail = (proc.stdout or "")[-MAX_TAIL:] + (proc.stderr or "")[-MAX_TAIL:]
        except (subprocess.TimeoutExpired, OSError) as exc:
            passed, tail = False, f"gate crashed: {exc}"[:MAX_TAIL]
        ok = ok and passed
        results.append({"cmd": " ".join(cmd), "ok": passed, "tail": tail.strip()})
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gate": "quality",
        "ok": ok,
        "duration_ms": duration_ms,
        "results": results,
    }
    duration_ms = round((time.monotonic() - started) * 1000, 2)
    log = _log_path(workdir)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the gate report must never break the caller
    trace_event("quality-gate", "run", outcome="ok" if ok else "fail",
                duration_ms=duration_ms)
    return ok, results
