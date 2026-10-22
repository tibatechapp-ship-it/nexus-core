"""Wiring test: /api/orchestrator/execute -> request_log.record (v1.37.0)."""

import json
from pathlib import Path

import pytest

pytest.importorskip("sse_starlette")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402


def _read(path: Path) -> list:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _fake_orch_module(monkeypatch):
    import src.orchestrator.orchestrator as orch_mod

    class FakeOrch:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, request, runner=None):
            return {
                "ok": True,
                "decomposed": False,
                "subtasks": [],
                "plan": {"risk": "med"},
                "output": "ok",
            }

    monkeypatch.setattr(orch_mod, "Orchestrator", FakeOrch)


def test_execute_writes_one_request_log(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))
    _fake_orch_module(monkeypatch)

    import nexus_agent

    client = TestClient(nexus_agent.app)
    response = client.post(
        "/api/orchestrator/execute",
        json={"request": "hello", "priority": "HIGH"},
    )
    assert response.status_code == 200
    rows = _read(log)
    assert len(rows) == 1, f"expected 1 entry, got {len(rows)}: {rows}"
    assert rows[0]["priority"] == "HIGH"
    assert rows[0]["outcome"] == "success"


def test_execute_defaults_priority_to_med(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))
    _fake_orch_module(monkeypatch)

    import nexus_agent

    client = TestClient(nexus_agent.app)
    response = client.post("/api/orchestrator/execute", json={"request": "hi"})
    assert response.status_code == 200
    rows = _read(log)
    assert len(rows) == 1
    assert rows[0]["priority"] == "MED"
