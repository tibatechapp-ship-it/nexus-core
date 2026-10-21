"""GET /api/orchestrator/metrics (v1.37.0)."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


def _seed(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_metrics_endpoint_returns_schema(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _seed(log, [
        {"schema": 1, "ts": now, "priority": "HIGH", "agent_id": "a", "outcome": "success"},
        {"schema": 1, "ts": now, "priority": "HIGH", "agent_id": "b", "outcome": "failed", "reason": "x"},
        {"schema": 1, "ts": now, "priority": "MED",  "agent_id": "c", "outcome": "success"},
        {"schema": 1, "ts": now, "priority": "LOW",  "agent_id": "d", "outcome": "success"},
    ])

    import nexus_agent
    client = TestClient(nexus_agent.app)
    r = client.get("/api/orchestrator/metrics?window_days=7")
    assert r.status_code == 200
    data = r.json()
    assert data["total_requests"] == 4
    assert data["by_priority"] == {"HIGH": 2, "MED": 1, "LOW": 1}
    assert data["failure_pct"] == pytest.approx(25.0)
    assert data["high_pct"] == pytest.approx(50.0)
    assert data["sample_sufficient"] is False
    assert isinstance(data["sampled_at"], str) and "T" in data["sampled_at"]


def test_metrics_endpoint_empty_log(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))

    import nexus_agent
    client = TestClient(nexus_agent.app)
    r = client.get("/api/orchestrator/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["total_requests"] == 0
    assert data["by_priority"] == {"HIGH": 0, "MED": 0, "LOW": 0}
