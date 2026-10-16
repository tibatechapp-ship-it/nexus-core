"""Smoke tests for the unified server (``nexus_agent.py``).

Offline and hermetic: a temp ``SessionStore`` replaces the real DB, the council
runs in deterministic offline mode (``router=None``), and the chat path uses a
fake router — so no network and no ``~/.nexus`` history is touched.

They also guard the *unification contract*: every wrapped Workbench route is
still present, and the NovaMind additions answer.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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

#: Representative Workbench routes that MUST survive the wrap.
_WORKBENCH_ROUTES = {
    "/", "/api/deliberate", "/api/health", "/api/build", "/api/builds",
    "/api/builds/{build_id}", "/api/craft", "/api/history",
    "/api/history/{rec_id}", "/api/topics", "/api/stats", "/api/review",
    "/manifest.json", "/sw.js", "/icon.svg", "/docs/swagger",
}


def _load_unified():
    """Load the repo-root ``nexus_agent.py`` by path (a fresh app per call)."""
    spec = importlib.util.spec_from_file_location("nexus_unified_server",
                                                  _ROOT / "nexus_agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexus_unified_server"] = module  # Pydantic resolves __module__ here
    spec.loader.exec_module(module)
    return module


class _FakeRouter:
    """Deterministic stand-in for novamind ``LLMRouter`` (no network)."""

    providers: list = []

    def generate(self, prompt, system="", **kwargs):  # noqa: ANN001, ANN003
        return {"ok": True, "text": "ردّ تجريبي من الموجّه الوهمي",
                "provider": "fake", "elapsed": 0.0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A unified module wired to a temp store + offline council + fake router."""
    mod = _load_unified()
    store = SessionStore(tmp_path / "sessions.db")
    genome = Genome(store)
    genome.seed()
    offline = Council(router=None, store=store, genome=genome)

    monkeypatch.setattr(mod, "get_store_singleton", lambda: store)
    monkeypatch.setattr(mod, "get_genome", lambda: genome)
    monkeypatch.setattr(mod, "get_council", lambda: offline)
    monkeypatch.setattr(mod, "get_router", lambda: _FakeRouter())

    # keep the wrapped history route off the real ~/.nexus store
    hist = CouncilHistory(history_dir=str(tmp_path / "hist"))
    monkeypatch.setattr("src.council.history.get_history", lambda: hist)

    return mod, TestClient(mod.app), store


# ── unification contract ────────────────────────────────────────────────────

def test_wraps_every_workbench_route(env):
    mod, _client, _store = env
    paths = {getattr(r, "path", "") for r in mod.app.routes}
    missing = _WORKBENCH_ROUTES - paths
    assert not missing, f"انكسر التفاف الوورك‌بنش، مسارات مفقودة: {missing}"


def test_status_reports_unified_components(env):
    mod, client, _store = env
    body = client.get("/api/status").json()
    assert body["nexus"] == "unified"
    comps = body["components"]
    assert comps["workbench"] is True
    assert comps["builder"] is True
    assert comps["council"] is True
    assert comps["council_members"] == len(mod.COUNCIL_MEMBERS)
    # contract used by scripts/bin/nexus: agents is a 3-way breakdown
    assert isinstance(comps["agents"], dict)
    assert comps["agents"]["framework"] == 20
    assert comps["agents"]["total"] == (comps["agents"]["framework"]
                                        + comps["agents"]["novamind"])
    assert comps["engine"] is True
    assert isinstance(comps["topics"], int) and comps["topics"] > 0


def test_diag_reports_mounts_and_routes(env):
    """``/api/diag``: مصدر الملف، حالة المحرّك، وعدّادات المسارات حقيقية."""
    mod, client, _store = env
    body = client.get("/api/diag").json()
    assert body["ok"] is True
    assert body["loaded_from"].endswith("nexus_agent.py")
    assert body["engine_ok"] is True
    assert body["council_ok"] is True
    # المحرّك المفروز يملك مسارات فعلية (كان يُعدّ 0 قبل إصلاح _engine.app)
    assert body["engine_routes_count"] > 0
    assert body["parent_routes_count"] > 0
    assert "/api/diag" in body["parent_routes"]
    assert body["version"] == mod._wb._app_version()


def test_mcp_tools_lists_framework_surface(env):
    """``/api/mcp/tools`` يعرض سطح أدوات MCP (وكلاء + أمان + ملفات + git)."""
    _mod, client, _store = env
    body = client.get("/api/mcp/tools").json()
    assert body["ok"] is True
    assert body["total"] >= 25
    groups = {t["group"] for t in body["tools"]}
    assert {"agents", "security", "workspace", "git"} <= groups
    names = {t["name"] for t in body["tools"]}
    assert "agent_analyst" in names
    assert "git_status" in names


def test_engine_mounted_as_catch_all(env):
    """المحرّف (unified_agent) مثبّت خلف كل المسارات — الوالد يفوز أولاً."""
    mod, client, _store = env
    assert mod.ENGINE_OK is True, mod.ENGINE_ERR
    mounts = [r for r in mod.app.routes if getattr(r, "path", "") == "/"]
    assert any(hasattr(r, "app") for r in mounts), "لا يوجد Mount للمحرّف"
    # مسار حصرّي للمحرّف يجب أن يجيب بعد التفافه
    assert client.get("/offline.html").status_code == 200


def test_agents_lists_real_builtins(env):
    _mod, client, _store = env
    body = client.get("/api/agents").json()
    assert body["total"] == 20
    ids = {a["id"] for a in body["agents"]}
    assert {"analyst", "coder", "architect"} <= ids
    assert all(a["group"] for a in body["agents"])


# ── wrapped workbench routes still answer ───────────────────────────────────

def test_wrapped_routes_answer(env):
    _mod, client, _store = env
    for path in ("/api/health", "/api/topics", "/api/stats"):
        assert client.get(path).status_code == 200, path


# ── NovaMind council ────────────────────────────────────────────────────────

def test_council_debate_offline(env):
    _mod, client, _store = env
    body = client.post("/api/council/debate",
                       json={"topic": "اختبار التوحيد", "rounds": 1}).json()
    assert body["ok"] is True
    result = body["result"]
    assert "verdict" in result
    assert result.get("members")


def test_council_stream_emits_sse(env):
    _mod, client, _store = env
    with client.stream("POST", "/api/council/stream",
                       json={"topic": "بثّ تجريبي", "rounds": 1}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        payload = [ln for ln in r.iter_lines() if ln.startswith("data:")]
    joined = "\n".join(payload)
    assert '"type": "session"' in joined
    assert "data: [DONE]" in joined


def test_council_sessions_list_and_404(env):
    _mod, client, _store = env
    body = client.get("/api/council/sessions").json()
    assert "sessions" in body
    assert client.get("/api/council/sessions/does-not-exist").status_code == 404


# ── Agent Genome ────────────────────────────────────────────────────────────

def test_genome_list_detail_patch_and_reset(env):
    _mod, client, _store = env
    agents = client.get("/api/genome").json()["agents"]
    assert agents, "الجينوم يجب أن يكون مبذوراً"
    aid = agents[0]["agent_id"]

    assert client.get(f"/api/genome/{aid}").status_code == 200
    assert client.get("/api/genome/missing").status_code == 404

    patched = client.patch(f"/api/genome/{aid}", json={"persona": "شخصية معدّلة"})
    assert patched.status_code == 200
    assert patched.json()["persona"] == "شخصية معدّلة"

    reset = client.post(f"/api/genome/{aid}/reset")
    assert reset.status_code == 200
    assert reset.json()["generation"] >= 1


def test_genome_export_and_import(env):
    _mod, client, _store = env
    exported = client.get("/api/genome/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers.get("content-disposition", "")
    body = exported.json()
    assert "agents" in body
    assert client.post("/api/genome/import", json=body).json()["imported"] >= 0


# ── chat ────────────────────────────────────────────────────────────────────

def test_chat_streams_chunk_then_done(env):
    _mod, client, _store = env
    with client.stream("POST", "/api/chat",
                       json={"message": "مرحبا", "agent": "analyst"}) as r:
        assert r.status_code == 200
        lines = [ln for ln in r.iter_lines() if ln.startswith("data:")]
    joined = "\n".join(lines)
    assert '"type": "plan"' in joined
    assert "ردّ تجريبي" in joined
    assert "data: [DONE]" in joined
