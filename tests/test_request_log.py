import json
from pathlib import Path
import pytest
from src.llm import request_log


@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))
    monkeypatch.delenv("NEXUS_REQUEST_LOG_MAX_BYTES", raising=False)
    return log


def _read(p):
    if not p.exists(): return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_record_appends(isolated_log):
    request_log.record(priority="MED", agent_id="a1", outcome="success")
    request_log.record(priority="HIGH", agent_id="a2", outcome="failed", reason="timeout")
    rows = _read(isolated_log)
    assert len(rows) == 2
    assert rows[0]["priority"] == "MED" and rows[0]["outcome"] == "success"
    assert "reason" not in rows[0]
    assert rows[1]["priority"] == "HIGH" and rows[1]["reason"] == "timeout"
    assert rows[0]["schema"] == request_log.SCHEMA_VERSION


def test_record_normalises(isolated_log):
    request_log.record(priority="medium", agent_id="a", outcome="success")
    request_log.record(priority="low", agent_id="a", outcome="success")
    request_log.record(priority="HIGH", agent_id="a", outcome="success")
    rows = _read(isolated_log)
    assert [r["priority"] for r in rows] == ["MED", "LOW", "HIGH"]


def test_record_never_raises(tmp_path, monkeypatch):
    bogus = tmp_path / "bogus"
    bogus.mkdir()
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(bogus))
    request_log.record(priority="MED", agent_id="a", outcome="success")


def test_aggregate_empty(isolated_log):
    out = request_log.aggregate(window_days=7)
    assert out["total_requests"] == 0
    assert out["by_priority"] == {"HIGH": 0, "MED": 0, "LOW": 0}
    assert out["failure_pct"] == 0.0
    assert out["high_pct"] == 0.0
    assert out["sample_sufficient"] is False
    assert "T" in out["sampled_at"]


def test_aggregate_counts(isolated_log):
    for p in ("HIGH", "HIGH", "MED", "MED", "MED", "LOW"):
        request_log.record(priority=p, agent_id="a", outcome="success")
    request_log.record(priority="HIGH", agent_id="a", outcome="failed")
    request_log.record(priority="MED", agent_id="a", outcome="failed", reason="x")
    out = request_log.aggregate(window_days=7)
    assert out["total_requests"] == 8
    assert out["by_priority"] == {"HIGH": 3, "MED": 4, "LOW": 1}
    assert out["failure_pct"] == pytest.approx(25.0)
    assert out["high_pct"] == pytest.approx(37.5)
    assert out["sample_sufficient"] is False


def test_aggregate_window(isolated_log):
    request_log.record(priority="MED", agent_id="a", outcome="success")
    old = {"schema": 1, "ts": "2020-01-01T00:00:00+00:00",
           "priority": "HIGH", "agent_id": "a", "outcome": "failed"}
    with isolated_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(old) + "\n")
    assert request_log.aggregate(window_days=7)["total_requests"] == 1
    assert request_log.aggregate(window_days=3650)["total_requests"] == 2


def test_rotation(isolated_log, monkeypatch):
    monkeypatch.setenv("NEXUS_REQUEST_LOG_MAX_BYTES", "200")
    for i in range(5):
        request_log.record(priority="MED", agent_id="a" + str(i), outcome="success")
    parent = isolated_log.parent
    backups = sorted(p.name for p in parent.iterdir() if p.name.startswith(isolated_log.name + "."))
    assert len(backups) >= 1
    for name in backups:
        suffix = name.rsplit(".", 1)[-1]
        assert suffix.isdigit()
        assert 1 <= int(suffix) <= request_log.BACKUPS
