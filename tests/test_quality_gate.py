"""Independent quality gate tests (M3.1) — separate process, JSONL report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.quality_gate.runner import _log_path, default_gates, run_gate

PY = sys.executable
REPO = Path(__file__).resolve().parent.parent


def _gate_log(tmp_path: Path) -> Path:
    return tmp_path / "runs" / "quality_gate.jsonl"


def test_green_gate(tmp_path: Path) -> None:
    ok, results = run_gate(tmp_path, gates=[[PY, "-c", "pass"]])
    assert ok is True and len(results) == 1 and results[0]["ok"] is True
    assert results[0]["cmd"].endswith("pass")


def test_red_gate(tmp_path: Path) -> None:
    ok, results = run_gate(tmp_path, gates=[[PY, "-c", "raise SystemExit(2)"]])
    assert ok is False and results[0]["ok"] is False


def test_gate_crash_is_a_failure(tmp_path: Path) -> None:
    ok, results = run_gate(tmp_path, gates=[["/no/such/binary"]])
    assert ok is False and "gate crashed" in results[0]["tail"]


def test_gate_timeout_is_a_failure(tmp_path: Path) -> None:
    ok, results = run_gate(tmp_path,
                           gates=[[PY, "-c", "import time; time.sleep(10)"]], timeout=1)
    assert ok is False and "crashed" in results[0]["tail"]


def test_report_appended_as_jsonl(tmp_path: Path) -> None:
    run_gate(tmp_path, gates=[[PY, "-c", "pass"]])
    run_gate(tmp_path, gates=[[PY, "-c", "pass"]])
    lines = _gate_log(tmp_path).read_text().splitlines()
    assert len(lines) == 2
    report = json.loads(lines[-1])
    assert report["gate"] == "quality" and report["ok"] is True
    assert {"ts", "gate", "ok", "duration_ms", "results"} <= set(report)
    assert isinstance(report["duration_ms"], float)


def test_env_overrides_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom" / "gate.jsonl"
    monkeypatch.setenv("NEXUS_QUALITY_GATE_LOG", str(custom))
    run_gate(tmp_path, gates=[[PY, "-c", "pass"]])
    assert custom.exists()
    assert _log_path(tmp_path) == custom


def test_log_failure_never_breaks_verdict(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "not-a-file"
    blocker.mkdir()
    monkeypatch.setenv("NEXUS_QUALITY_GATE_LOG", str(blocker))
    ok, results = run_gate(tmp_path, gates=[[PY, "-c", "pass"]])
    assert ok is True and results[0]["ok"] is True


def test_default_gates_shape() -> None:
    gates = default_gates()
    assert len(gates) == 3
    assert gates[0][1:3] == ["-m", "pytest"]
    assert gates[1][1:3] == ["-m", "compileall"]
    assert gates[2][-1] == "scripts/check_annotations.py"


def test_annotations_gate_green_on_repo_root() -> None:
    """The real annotation gate runs green on this repo (integration)."""
    ok, results = run_gate(REPO, gates=[[PY, "scripts/check_annotations.py"]], timeout=120)
    assert ok is True, results[0]["tail"]


def test_trace_event_fired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(trace))
    run_gate(tmp_path, gates=[[PY, "-c", "pass"]])
    event = json.loads(trace.read_text().splitlines()[-1])
    assert event["agent"] == "quality-gate" and event["outcome"] == "ok"
