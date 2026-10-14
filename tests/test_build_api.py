"""API smoke tests for the Builder endpoints (offline — no live council call).

Uses a temp build root and a temp history dir so the real ``~/.nexus/data``
store is never touched.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from src.council.engine import CouncilResult  # noqa: E402
from src.council.history import CouncilHistory  # noqa: E402


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_BUILDS", str(tmp_path / "builds"))
    hist = CouncilHistory(history_dir=str(tmp_path / "hist"))
    monkeypatch.setattr(hist, "_get_rag", lambda: None)  # لا نكتب في rag.db الحقيقي
    result = CouncilResult(
        verdict="approve", score=0.8, consensus=True, rounds=1,
        transcript=[{"member": "analyst",
                     "response": "آمن\n[الحكم: موافق]\n[التوصية: استخدم sqlite]"}],
        elapsed=1.0,
    )
    rec_id = hist.save(result, query="هل نستخدم sqlite؟", category="test")
    monkeypatch.setattr("src.council.history.get_history", lambda: hist)

    import main
    return TestClient(main.app), rec_id


def test_health_exposes_builder_and_embeddings(seeded):
    client, _ = seeded
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["builder"] is True
    assert "embeddings" in body


def test_build_from_decision_id_offline(seeded):
    client, rec_id = seeded
    resp = client.post("/api/build", json={"decision_id": rec_id, "use_llm": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["kind"] == "plan"
    paths = {f["path"] for f in body["files"]}
    assert {"PLAN.md", "decision.json"} <= paths
    assert body["proof"]["ok"] is True


def test_builds_list_and_detail(seeded):
    client, rec_id = seeded
    created = client.post("/api/build", json={"decision_id": rec_id, "use_llm": False}).json()
    listed = client.get("/api/builds").json()["items"]
    assert any(item["build_id"] == created["build_id"] for item in listed)
    detail = client.get(f"/api/builds/{created['build_id']}").json()
    assert detail["build_id"] == created["build_id"]


def test_build_missing_input_errors(seeded):
    client, _ = seeded
    body = client.post("/api/build", json={}).json()
    assert body["ok"] is False and "error" in body


def test_build_unknown_decision_errors(seeded):
    client, _ = seeded
    body = client.post("/api/build", json={"decision_id": "decision_nope"}).json()
    assert body["ok"] is False


def test_build_detail_not_found(seeded):
    client, _ = seeded
    assert "error" in client.get("/api/builds/does-not-exist").json()
