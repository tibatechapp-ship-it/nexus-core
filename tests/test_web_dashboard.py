"""Tests for the read-only dashboard (Week-1): /api/dashboard + /dashboard page.

Offline by construction: the aggregation endpoint only reads in-process state
(registry sizes, run tracker, council history briefs) — it never executes an
agent, and every degraded source must keep ``ok`` true.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import src.council.history as hist_mod
from src.web import app as webapp
from src.web.app import app

client = TestClient(app)

PAGE_LABELS = ("الوكلاء النشطون", "المهام الجارية", "آخر القرارات")


@pytest.fixture(autouse=True)
def clean_runs() -> Any:
    webapp._runs.clear()
    yield
    webapp._runs.clear()


# ───────────────────────────── API ─────────────────────────────

def test_dashboard_api_shape_and_live_registry() -> None:
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["agents"]["total"] > 0          # real registry, loaded offline
    assert isinstance(body["agents"]["by_category"], dict)
    assert body["tasks_running"] == 0
    assert isinstance(body["recent_decisions"], list)
    assert "T" in body["generated_at"]          # UTC ISO-8601


def test_dashboard_api_reflects_run_tracker() -> None:
    before = client.get("/api/dashboard").json()["tasks_running"]
    rid = webapp._run_started()
    try:
        during = client.get("/api/dashboard").json()["tasks_running"]
    finally:
        webapp._run_finished(rid)
    after = client.get("/api/dashboard").json()["tasks_running"]
    assert during == before + 1
    assert after == before


def test_dashboard_api_survives_agent_run_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A heavy endpoint that fails must still release its run slot."""
    import nova.registry as reg_mod

    class _Boom:
        def run(self, prompt: str) -> str:
            raise RuntimeError("boom")

    class _Reg:
        def __len__(self) -> int:
            return 1

        def load_agent(self, name: str) -> Any:
            return _Boom()

    monkeypatch.setattr(reg_mod, "REGISTRY", _Reg())
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": False}).json()
    assert body["ok"] is False and "boom" in body["error"]
    assert client.get("/api/dashboard").json()["tasks_running"] == 0


def test_dashboard_api_recent_decisions_from_history(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeHist:
        def list_recent(self, n: int = 5) -> list[dict[str, Any]]:
            return [{"question": "هل ندفع؟", "verdict": "approve"},
                    {"question": "ثاني", "verdict": "reject"}]

    monkeypatch.setattr(hist_mod, "get_history", lambda: _FakeHist())
    body = client.get("/api/dashboard").json()
    assert body["ok"] is True
    assert [d["verdict"] for d in body["recent_decisions"]] == ["approve", "reject"]


def test_dashboard_api_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("history down")

    monkeypatch.setattr(hist_mod, "get_history", _boom)
    body = client.get("/api/dashboard").json()
    assert body["ok"] is True                       # never dies on a bad source
    assert body["recent_decisions"] == []
    assert "history down" in body["decisions_error"]


# ───────────────────────────── page ─────────────────────────────

def test_dashboard_page_serves_readonly_html() -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]
    for label in PAGE_LABELS:
        assert label in r.text
    assert 'dir="rtl"' in r.text
    assert "<script" not in r.text.lower()          # read-only: zero JS


def test_dashboard_page_escapes_decision_text(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeHist:
        def list_recent(self, n: int = 5) -> list[dict[str, Any]]:
            return [{"question": "<script>alert(1)</script>", "verdict": "x"}]

    monkeypatch.setattr(hist_mod, "get_history", lambda: _FakeHist())
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
