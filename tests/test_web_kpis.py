"""KPI tests (M3.3): every dashboard number must match the logs literally.

محكمة عبر التجاوزات المعيارية NEXUS_TRACE_PATH / NEXUS_QUALITY_GATE_LOG —
لا قراءة من جذر المستودع إطلاقاً.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.web.app import app
from src.web.kpis import compute_kpis

client = TestClient(app)


def _trace_line(agent: str = "coder", tool: str = "analyze",
                outcome: str = "ok", duration_ms: Any = 100) -> dict:
    return {"ts": "2026-01-01T00:00:00+00:00", "agent": agent, "tool": tool,
            "outcome": outcome, "duration_ms": duration_ms}


@pytest.fixture()
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    trace = tmp_path / "trace.jsonl"
    gate = tmp_path / "gate.jsonl"
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(trace))
    monkeypatch.setenv("NEXUS_QUALITY_GATE_LOG", str(gate))
    return trace, gate


# ───────────────────────────── الحساب ─────────────────────────────

def test_numbers_match_logs_exactly(logs: tuple) -> None:
    trace, gate = logs
    trace.write_text("\n".join(json.dumps(e) for e in [
        _trace_line("coder", "analyze", "ok", 100),
        _trace_line("coder", "detect", "ok", 300),
        _trace_line("council", "run", "fail", 200),
    ]) + "\n", encoding="utf-8")
    gate.write_text(json.dumps(
        {"ts": "t", "gate": "pytest", "ok": True, "duration_ms": 50.0,
         "results": []}) + "\n", encoding="utf-8")
    k = compute_kpis()
    assert k["trace"]["events"] == 3
    assert k["trace"]["ok_rate"] == round(2 / 3, 4)
    assert k["trace"]["by_agent"] == {"coder": 2, "council": 1}
    assert k["trace"]["p50_ms"] == 200
    assert k["trace"]["p95_ms"] == 300
    assert k["gate"]["runs"] == 1
    assert k["gate"]["ok_rate"] == 1.0
    assert k["gate"]["p50_ms"] == 50.0


def test_missing_logs_report_unavailable(logs: tuple) -> None:
    k = compute_kpis()
    assert k["trace"]["available"] is False and k["trace"]["events"] == 0
    assert k["trace"]["ok_rate"] is None and k["trace"]["p50_ms"] is None
    assert k["gate"]["available"] is False and k["gate"]["runs"] == 0


def test_malformed_lines_are_skipped(logs: tuple) -> None:
    trace, _ = logs
    trace.write_text(
        json.dumps(_trace_line()) + "\nNOT-JSON\n\n", encoding="utf-8")
    k = compute_kpis()
    assert k["trace"]["events"] == 1 and k["trace"]["ok_rate"] == 1.0


def test_non_numeric_durations_are_ignored(logs: tuple) -> None:
    trace, _ = logs
    trace.write_text(json.dumps(
        _trace_line(duration_ms="fast")) + "\n", encoding="utf-8")
    k = compute_kpis()
    assert k["trace"]["p50_ms"] is None and k["trace"]["p95_ms"] is None
    assert k["trace"]["ok_rate"] == 1.0


def test_explicit_paths_override_env(tmp_path: Path) -> None:
    other = tmp_path / "other.jsonl"
    other.write_text(json.dumps(_trace_line(duration_ms=5)) + "\n",
                     encoding="utf-8")
    k = compute_kpis(trace_path=other, gate_path=tmp_path / "absent.jsonl")
    assert k["trace"]["events"] == 1
    assert k["gate"]["available"] is False


def test_limit_zero_yields_empty_window(logs: tuple) -> None:
    trace, _ = logs
    trace.write_text(json.dumps(_trace_line()) + "\n", encoding="utf-8")
    k = compute_kpis(limit=0)
    assert k["trace"]["events"] == 0 and k["trace"]["available"] is False
    assert k["window"] == 0


# ───────────────────────────── التكامل مع اللوحة ─────────────────────────────

def test_endpoint_matches_logs(logs: tuple) -> None:
    trace, _ = logs
    trace.write_text(json.dumps(
        _trace_line("coder", "plan", "ok", 42)) + "\n", encoding="utf-8")
    res = client.get("/api/kpis?limit=50")
    assert res.status_code == 200 and res.json()["ok"] is True
    kpis = res.json()["kpis"]
    assert kpis["trace"]["events"] == 1
    assert kpis["trace"]["p50_ms"] == 42
    assert kpis["window"] == 50


def test_dashboard_page_shows_kpi_section(logs: tuple) -> None:
    trace, _ = logs
    trace.write_text(json.dumps(
        _trace_line("coder", "analyze", "ok", 10)) + "\n", encoding="utf-8")
    page = client.get("/dashboard").text
    assert "مؤشرات حية (KPIs)" in page
    assert "الأثر" in page and "البوابة" in page
    assert "10ms" in page


def test_dashboard_kpis_escape_agent_names(logs: tuple) -> None:
    trace, _ = logs
    evil = "<script>alert(1)</script>"
    trace.write_text(json.dumps(
        _trace_line(evil, "x", "ok", 1)) + "\n", encoding="utf-8")
    page = client.get("/dashboard").text
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
