"""Endpoint tests for ``POST /api/orchestrator/execute`` (v1.22.0).

Hermetic: loads the repo-root gateway by path, replaces the store/router/council
with temp/offline fakes (same pattern as ``tests/test_nexus_agent.py``), and
drives the endpoint through a ``TestClient``. No network, no ``~/.nexus``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sse_starlette")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from src.council.history import CouncilHistory  # noqa: E402
from src.novamind.council import Council  # noqa: E402
from src.novamind.core.session_store import SessionStore  # noqa: E402
from src.novamind.genome import Genome  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


def _load_unified() -> Any:
    spec = importlib.util.spec_from_file_location("nexus_orch_exec_server",
                                                  _ROOT / "nexus_agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexus_orch_exec_server"] = module
    spec.loader.exec_module(module)
    return module


class _FakeRouter:
    """Deterministic router: dict return, no ``json_mode`` (project shape)."""

    providers: list = []

    def __init__(self, text: str = "تحليل تجريبي", ok: bool = True) -> None:
        self._text = text
        self._ok = ok

    def generate(self, prompt: str, system: str = "", **kwargs: Any) -> dict[str, Any]:
        return {"ok": self._ok, "text": self._text, "provider": "fake",
                "elapsed": 0.0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    mod = _load_unified()
    # This suite asserts the FULL verdict contract (per-juror details), which is
    # a developer/verbose concern — the black box is covered separately in
    # tests/test_invisible_council.py.
    monkeypatch.setenv("NEXUS_UI_VERBOSE", "1")
    store = SessionStore(tmp_path / "sessions.db")
    genome = Genome(store)
    genome.seed()
    offline = Council(router=None, store=store, genome=genome)

    monkeypatch.setattr(mod, "get_store_singleton", lambda: store)
    monkeypatch.setattr(mod, "get_genome", lambda: genome)
    monkeypatch.setattr(mod, "get_council", lambda: offline)
    monkeypatch.setattr(mod, "get_router", lambda: _FakeRouter())

    hist = CouncilHistory(history_dir=str(tmp_path / "hist"))
    monkeypatch.setattr("src.council.history.get_history", lambda: hist)

    return mod, TestClient(mod.app), store


# ── contract ────────────────────────────────────────────────────────────────

def test_execute_route_is_registered(env):
    mod, _client, _store = env
    paths = {getattr(r, "path", "") for r in mod.app.routes}
    assert "/api/orchestrator/execute" in paths
    assert "/api/orchestrator/plan" in paths


def test_execute_route_survives_the_mount_boundary(env):
    """The route must sit BEFORE the catch-all Mount (parent-routes-win)."""
    from starlette.routing import Mount

    mod, _client, _store = env
    mount_idx = next(
        (i for i, r in enumerate(mod.app.routes) if isinstance(r, Mount)), None)
    exec_idx = next(
        (i for i, r in enumerate(mod.app.routes)
         if str(getattr(r, "path", "")) == "/api/orchestrator/execute"), None)
    assert mount_idx is not None and exec_idx is not None
    assert exec_idx < mount_idx


def test_execute_low_risk_runs_agent_and_skips_jury(env):
    _mod, client, _store = env
    r = client.post("/api/orchestrator/execute",
                    json={"request": "add comment to foo"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["jury"] is None  # LOW risk never convenes the jury
    assert body["output"] == "تحليل تجريبي"
    assert body["plan"]["agent"]
    assert body["plan"]["risk"] == "low"


def test_execute_empty_request_is_rejected(env):
    _mod, client, _store = env
    r = client.post("/api/orchestrator/execute", json={"request": "   "})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "empty request"}


def test_execute_high_risk_convenes_the_jury_with_the_real_router(env):
    """The latent defect guard: HIGH risk + real (dict) router must NOT TypeError.

    Without ``adapt_llm`` the jury fails closed with
    ``unexpected keyword argument 'json_mode'`` → an empty/abstained verdict.
    With the adapter, the fake router's answer is parsed as the member JSON.
    """
    mod, client, _store = env
    # make every jury member approve
    monkeypatch_router = _FakeRouter(text='{"approved": true, "confidence": 0.9}')
    mod.get_router = lambda: monkeypatch_router  # type: ignore[assignment]
    r = client.post("/api/orchestrator/execute",
                    json={"request": "delete genome entries"})
    body = r.json()
    assert body["plan"]["risk"] == "high"
    assert body["jury"] is not None
    # every member parsed a real JSON verdict (not "no_llm"/"error:...")
    for verdict in body["jury"]["member_verdicts"].values():
        assert not verdict.get("abstain"), verdict
    assert body["jury"]["approved"] is True
    assert body["ok"] is True


def test_execute_high_risk_jury_rejection_fails_closed(env):
    mod, client, _store = env
    mod.get_router = lambda: _FakeRouter(  # type: ignore[assignment]
        text='{"approved": false, "confidence": 0.9, "issues": ["unsafe"]}')
    r = client.post("/api/orchestrator/execute",
                    json={"request": "delete genome entries"})
    body = r.json()
    assert body["jury"]["approved"] is False
    assert body["ok"] is False
    assert "unsafe" in body["jury"]["blocking_issues"]


def test_execute_reports_runner_failure_as_not_ok(env):
    mod, client, _store = env
    mod.get_router = lambda: _FakeRouter(ok=False)  # type: ignore[assignment]
    r = client.post("/api/orchestrator/execute",
                    json={"request": "add a comment to foo"})
    body = r.json()
    assert body["ok"] is False
    assert body["output"]  # an honest error string, not None


def test_execute_records_a_metric(env, tmp_path, monkeypatch):
    """The endpoint must append one metrics row per execution (v1.25.0)."""
    from src.orchestrator import _metrics

    mod, client, _store = env
    metrics_path = tmp_path / "metrics.json"
    monkeypatch.setenv("NEXUS_METRICS_PATH", str(metrics_path))

    r = client.post("/api/orchestrator/execute",
                    json={"request": "write a sum function and test it"})
    assert r.json()["ok"] is True

    rows = _metrics.load(metrics_path)
    assert len(rows) == 1
    assert rows[0]["decomposed"] is True
    assert rows[0]["agents"] == ["coder", "tester"]


def test_a_broken_metrics_log_never_breaks_execution(env, tmp_path, monkeypatch):
    """A failing recorder is swallowed — execution stays ok (v1.25.0)."""
    mod, client, _store = env

    def _boom(*_a, **_k):
        raise RuntimeError("metrics exploded")

    monkeypatch.setattr("src.orchestrator._metrics.record", _boom)
    r = client.post("/api/orchestrator/execute",
                    json={"request": "write a sum function and test it"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_plan_endpoint_still_works(env):
    _mod, client, _store = env
    r = client.post("/api/orchestrator/plan", json={"request": "read the docs"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "agent" in body and "risk" in body
