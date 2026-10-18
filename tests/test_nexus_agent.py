"""Smoke tests for the unified server (``nexus_agent.py``).

Offline and hermetic: a temp ``SessionStore`` replaces the real DB, the council
runs in deterministic offline mode (``router=None``), and the chat path uses a
fake router — so no network and no ``~/.nexus`` history is touched.

They also guard the *unification contract*: every wrapped Workbench route is
still present, and the NovaMind additions answer.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
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


class _DeadRouter:
    """A router that cannot answer — the offline/no-provider path."""

    providers: list = []

    def generate(self, prompt, system="", **kwargs):  # noqa: ANN001, ANN003
        return {"ok": False, "error": "لا مزود متاح"}


def _capture_outcomes(monkeypatch, calls: list) -> None:
    """Intercept the genome's task channel (the real genome is never touched)."""

    class _Recorder:
        def observe_outcome(self, agent_id, ok, *, duration=None,  # noqa: ANN001
                            quality=None, task=""):  # noqa: ANN001
            calls.append({"agent": agent_id, "ok": ok,
                          "duration": duration, "task": task})

    monkeypatch.setattr("src.novamind.genome_v2.get_genome_v2",
                        lambda: _Recorder())


def test_chat_folds_the_run_into_the_genome(env, monkeypatch):
    """v1.16.0: كل ردّ حقيقي يصل قناة نتائج المهام في الجينوم."""
    _mod, client, _store = env
    calls: list = []
    _capture_outcomes(monkeypatch, calls)

    with client.stream("POST", "/api/chat",
                       json={"message": "اكتب اختبار", "agent": "analyst"}) as r:
        assert r.status_code == 200
        list(r.iter_lines())

    assert len(calls) == 1
    assert calls[0]["agent"] == "analyst"
    assert calls[0]["ok"] is True
    assert calls[0]["duration"] >= 0.0
    assert calls[0]["task"] == "اكتب اختبار"


def test_chat_records_a_failure_when_no_provider_answers(env, monkeypatch):
    """فشل المزود = فشل حقيقي، لا يُخفي التسجيل."""
    mod, client, _store = env
    monkeypatch.setattr(mod, "get_router", lambda: _DeadRouter())
    calls: list = []
    _capture_outcomes(monkeypatch, calls)

    with client.stream("POST", "/api/chat", json={"message": "مرحبا"}) as r:
        assert r.status_code == 200
        list(r.iter_lines())

    assert len(calls) == 1
    assert calls[0]["ok"] is False


def test_a_broken_genome_never_breaks_chat(env, monkeypatch):
    """الجينوم رصدٌ فقط — انهياره لا يفشل الطلب."""

    def _boom():  # noqa: ANN202
        raise RuntimeError("genome down")

    _mod, client, _store = env
    monkeypatch.setattr("src.novamind.genome_v2.get_genome_v2", _boom)

    with client.stream("POST", "/api/chat", json={"message": "مرحبا"}) as r:
        assert r.status_code == 200
        joined = "\n".join(ln for ln in r.iter_lines()
                           if ln.startswith("data:"))
    assert "ردّ تجريبي" in joined
    assert "data: [DONE]" in joined


def test_the_chat_agent_id_defaults_when_none_is_given(env, monkeypatch):
    _mod, client, _store = env
    calls: list = []
    _capture_outcomes(monkeypatch, calls)

    with client.stream("POST", "/api/chat", json={"message": "مرحبا"}) as r:
        assert r.status_code == 200
        list(r.iter_lines())

    assert calls and calls[0]["agent"] == "default"


def test_an_empty_message_is_not_a_task(env, monkeypatch):
    """رسالة فارغة = لا تشغيل أصلاً، فلا تُلوّث الجينوم بفشل وهمي."""
    _mod, client, _store = env
    calls: list = []
    _capture_outcomes(monkeypatch, calls)

    with client.stream("POST", "/api/chat", json={"message": "   "}) as r:
        assert r.status_code == 200
        list(r.iter_lines())

    assert calls == []


# ── access guard: token + rate limit + audit ──────────────────────────────

def test_status_reports_the_access_guard(env):
    """``/api/status`` يحمل حالة الحارس (بلا تسريب التوكن أبداً)."""
    _mod, client, _store = env
    guard = client.get("/api/status").json()["guard"]
    assert isinstance(guard["auth"], bool)
    assert guard["rate"] >= 0 and guard["window"] >= 0.0
    assert guard["header"] == "x-auth-token"
    assert guard["methods"] == ["DELETE", "PATCH", "POST", "PUT"]
    assert guard["audit"] is None or isinstance(guard["audit"], str)


def test_reads_stay_open_when_a_token_is_required(env):
    """المصادقة تحمي الطرق المتغيّرة فقط — القراءات تمرّ دائماً."""
    mod, client, _store = env
    mod.GUARD.token = "s3cret"
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_mutating_calls_need_the_token(env):
    mod, client, _store = env
    mod.GUARD.token = "s3cret"
    denied = client.post("/api/council/debate", json={"topic": "قرار"})
    assert denied.status_code == 401
    assert denied.json()["ok"] is False
    assert "x-auth-token" in denied.json()["error"]
    ok = client.post("/api/council/debate", json={"topic": "قرار"},
                     headers={"X-Auth-Token": "s3cret"})
    assert ok.status_code == 200


def test_a_bad_token_is_refused_before_the_handler_runs(env):
    """حتى مسار غير موجود يردّ 401 لا 404 عندما تكون المصادقة فعّالة."""
    mod, client, _store = env
    mod.GUARD.token = "s3cret"
    resp = client.post("/api/definitely-not-a-route", json={})
    assert resp.status_code == 401


def test_rate_limit_returns_429_with_retry_after(env):
    from src.security.access import RateLimiter

    mod, client, _store = env
    mod.GUARD.limiter = RateLimiter(1, 30.0)
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 200
    limited = client.post("/api/chat", json={"message": "hi"})
    assert limited.status_code == 429
    assert limited.json()["error"] == "rate limit exceeded"
    assert 0 < int(limited.headers["Retry-After"]) <= 30


def test_audit_log_records_every_request(env, tmp_path):
    from src.security.access import AuditLog

    mod, client, _store = env
    target = tmp_path / "audit.jsonl"
    mod.GUARD.audit = AuditLog(target)
    client.get("/api/status")
    text = target.read_text(encoding="utf-8")
    assert '"/api/status"' in text and '"status": 200' in text
    assert '"method": "GET"' in text


# ── single-instance lock (يمنع نسختين من البوابة) ─────────────────────────

def test_instance_lock_is_exclusive_per_port_and_released_on_close(
        env, tmp_path, monkeypatch):
    """قفل واحد لكل منفذ: النسخة الثانية تُرفض، والإغلاق يُفلت القفل."""
    mod, _client, _store = env
    monkeypatch.setenv("NEXUS_LOCK_DIR", str(tmp_path))

    first = mod.acquire_instance_lock(8123)
    assert first is not None
    # نفس المنفذ، فتحة ثانية (= نسخة أخرى) ⇒ تُرفض
    assert mod.acquire_instance_lock(8123) is None
    # الملف يحمل pid الحامل (دليل حيّ لمن يملك القفل)
    assert (tmp_path / "nexus-agent-8123.lock").read_text().strip() == str(os.getpid())

    first.close()  # إغلاق = موت العملية = فلتة flock
    second = mod.acquire_instance_lock(8123)
    assert second is not None
    second.close()

    # منفذ مختلف لا يتقاطع مع هذا القفل أبداً
    other = mod.acquire_instance_lock(8124)
    assert other is not None
    other.close()


def test_main_refuses_to_start_when_another_instance_holds_the_lock(
        env, tmp_path, monkeypatch):
    """نسخة ثانية تنتهي بـ SystemExit(1) قبل uvicorn — لا يتيم ولا تكرار."""
    mod, _client, _store = env
    monkeypatch.setenv("NEXUS_LOCK_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_PORT", "8131")

    holder = mod.acquire_instance_lock(8131)
    assert holder is not None
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert excinfo.value.code == 1
    holder.close()


def test_main_starts_when_the_lock_is_free(env, tmp_path, monkeypatch):
    """بلا نسخة ثانية ⇒ main() تصل إلى uvicorn.run على المنفذ الصحيح."""
    mod, _client, _store = env
    monkeypatch.setenv("NEXUS_LOCK_DIR", str(tmp_path))
    monkeypatch.setenv("NEXUS_PORT", "8132")

    calls: list = []
    fake_uvicorn = types.SimpleNamespace(
        run=lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    mod.main()
    assert len(calls) == 1
    assert calls[0][1]["port"] == 8132
