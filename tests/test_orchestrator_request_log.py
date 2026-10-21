"""Wiring test: /api/orchestrator/execute -> request_log.record (v1.37.0)."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


def _read(path):
    if not path.exists(): return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_execute_writes_one_request_log(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))

    import nexus_agent

    # Mock the orchestrator so no LLM/Ollama is needed
    class FakeOrch:
        def __init__(self, *a, **kw): pass
        def execute(self, request, runner=None):
            return {"ok": True, "decomposed": False, "subtasks": [],
                    "plan": {"risk": "med"}, "output": "ok"}

    import src.orchestrator.orchestrator as _orch_mod
    monkeypatch.setattr(_orch_mod, "Orchestrator", FakeOrch)

    client = TestClient(nexus_agent.app)
    r = client.post("/api/orchestrator/execute",
                    json={"request": "hello", "priority": "HIGH"})
    assert r.status_code == 200
    rows = _read(log)
    assert len(rows) == 1, f"expected 1 entry, got {len(rows)}: {rows}"
    assert rows[0]["priority"] == "HIGH"
    assert rows[0]["outcome"] == "success"


def test_execute_defaults_priority_to_med(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))

    import nexus_agent
    class FakeOrch:
        def __init__(self, *a, **kw): pass
        def execute(self, request, runner=None):
            return {"ok": True, "decomposed": False, "subtasks": [],
                    "plan": {"risk": "med"}, "output": "ok"}

    import src.orchestrator.orchestrator as _orch_mod
    monkeypatch.setattr(_orch_mod, "Orchestrator", FakeOrch)

    client = TestClient(nexus_agent.app)
    r = client.post("/api/orchestrator/execute", json={"request": "hi"})
    assert r.status_code == 200
    rows = _read(log)
    assert len(rows) == 1
    assert rows[0]["priority"] == "MED"
