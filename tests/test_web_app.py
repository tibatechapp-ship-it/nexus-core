"""Tests for src/web/app.py — the FastAPI dashboard (offline, no live LLM)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import nova.registry as reg_mod
import src.council.rag_bridge as bridge_mod
import src.council.topics as topics_mod
import src.orchestrator.hybrid_router as hybrid_mod
import src.orchestrator.supervisor as sup_mod
from src.web import app as webapp
from src.web.app import app

client = TestClient(app)


# ───────────────────────────── fakes ─────────────────────────────

class _FakeAgent:
    def run(self, prompt: str) -> str:
        return f"ran:{prompt}"


class _NoMethodAgent:
    pass


class _FakeRegistry:
    def __init__(self, agent: Any = None) -> None:
        self._agent = agent

    def __len__(self) -> int:
        return 1

    def load_agent(self, name: str) -> Any:
        if name == "nomethod":
            return _NoMethodAgent()
        if self._agent is None:
            raise KeyError(name)
        return self._agent


class _FakeBridge:
    def __init__(self) -> None:
        self.engine = SimpleNamespace(MAX_ROUNDS=5)
        self.remembered: list[str] = []

    def enrich_prompt(self, prompt: str, k: int = 3) -> str:
        return f"enriched::{prompt}"

    def remember(self, text: str) -> str:
        self.remembered.append(text)
        return "d-1"

    def recall(self, q: str, k: int = 5) -> list[Any]:
        return [SimpleNamespace(id="d1", text="مرجع", distance=0.1)]

    def deliberate_with_memory(self, question: str) -> Any:
        return SimpleNamespace(
            verdict="approve", score=0.9, rounds=1, consensus=0.8, elapsed=0.01,
            transcript=[{"phase": "d", "member": "m", "response": "r" * 600}],
            security_events=[])


@pytest.fixture
def fake_council(monkeypatch: pytest.MonkeyPatch) -> _FakeBridge:
    b = _FakeBridge()
    monkeypatch.setattr(bridge_mod, "get_council_bridge", lambda: b)
    return b


@pytest.fixture(autouse=True)
def reset_status_cache() -> Any:
    webapp._status_cache["data"] = None
    webapp._status_cache["ts"] = 0
    yield
    webapp._status_cache["data"] = None
    webapp._status_cache["ts"] = 0


# ───────────────────────────── basics ─────────────────────────────

def test_index_serves_dashboard() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]
    assert len(r.text) > 1000


def test_status_reports_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert {"version", "agents", "rag_docs"} <= set(body)
    assert isinstance(body["agents"], int) and body["agents"] > 0
    assert webapp._status_cache["data"] == body


def test_status_second_call_is_served_from_cache() -> None:
    client.get("/api/status")
    ts = webapp._status_cache["ts"]
    webapp._status_cache["data"] = {"cached": True}
    webapp._status_cache["ts"] = ts
    assert client.get("/api/status").json() == {"cached": True}


def test_status_rag_failure_degrades_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.agent_rag_bridge as rag_mod

    def _boom() -> Any:
        raise RuntimeError("no db")

    monkeypatch.setattr(rag_mod, "get_bridge", _boom)
    assert client.get("/api/status").json()["rag_docs"] == 0


def test_agents_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry())
    monkeypatch.setattr(reg_mod, "agents_by_category", lambda c: ["a"])
    body = client.get("/api/agents").json()
    assert body["total"] == 1 and "code" in body["by_category"]


# ───────────────────────────── agent run ─────────────────────────────

def test_agent_run_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry(_FakeAgent()))
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": False}).json()
    assert body["ok"] is True and body["result"] == "ran:hi" and body["method"] == "run"


def test_agent_run_with_rag_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry(_FakeAgent()))
    import src.memory.agent_rag_bridge as rag_mod

    class _B:
        def enrich_prompt(self, prompt: str, k: int = 3) -> str:
            return f"ctx::{prompt}"

    monkeypatch.setattr(rag_mod, "get_bridge", lambda: _B())
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": True}).json()
    assert body["ok"] is True and body["result"] == "ran:ctx::hi"


def test_agent_run_enrichment_failure_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry(_FakeAgent()))
    import src.memory.agent_rag_bridge as rag_mod

    monkeypatch.setattr(rag_mod, "get_bridge",
                        lambda: (_ for _ in ()).throw(RuntimeError("x")))
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": True}).json()
    assert body["ok"] is True and body["result"] == "ran:hi"


def test_agent_run_enrichment_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry(_FakeAgent()))
    import src.memory.agent_rag_bridge as rag_mod

    class _B:
        def enrich_prompt(self, prompt: str, k: int = 3) -> str:
            return prompt                      # nothing new to add

    monkeypatch.setattr(rag_mod, "get_bridge", lambda: _B())
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "same", "use_rag": True}).json()
    assert body["ok"] is True and body["result"] == "ran:same"


def test_agent_run_no_method(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry(_NoMethodAgent()))
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": False}).json()
    assert body["ok"] is False and "لا توجد طريقة" in body["error"]


def test_agent_run_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg_mod, "REGISTRY", _FakeRegistry(None))
    body = client.post("/api/agent/run",
                       json={"agent": "x", "prompt": "hi", "use_rag": False}).json()
    assert body["ok"] is False and "error" in body


# ───────────────────────────── rag ─────────────────────────────

def test_rag_add_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    b = _FakeBridge()
    monkeypatch.setattr("src.memory.agent_rag_bridge.get_bridge", lambda: b)
    added = client.post("/api/rag/add", json={"text": "شيء مهم"}).json()
    assert added == {"ok": True, "doc_id": "d-1"}
    q = client.get("/api/rag/query", params={"q": "شيء", "k": 3}).json()
    assert q["ok"] is True and q["results"][0]["text"] == "مرجع"


# ───────────────────────────── council ─────────────────────────────

def test_council_deliberate_success(fake_council: _FakeBridge) -> None:
    body = client.post("/api/council/deliberate",
                       json={"question": "هل ندفع؟"}).json()
    assert body["ok"] is True and body["verdict"] == "approve"
    assert body["transcript"][0]["response"] == "r" * 500
    assert fake_council.engine.MAX_ROUNDS == 1


def test_council_deliberate_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge_mod, "get_council_bridge",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    body = client.post("/api/council/deliberate", json={"question": "x"}).json()
    assert body["ok"] is False and body["error"] == "down"


def test_council_topics_endpoint() -> None:
    body = client.get("/api/council/topics").json()
    assert body["ok"] is True and isinstance(body["categories"], dict)


def test_council_topics_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise RuntimeError("topics down")

    monkeypatch.setattr(topics_mod, "list_categories", _boom)
    assert client.get("/api/council/topics").json()["ok"] is False


def test_council_history_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.history as hist_mod

    def _boom() -> Any:
        raise RuntimeError("history down")

    monkeypatch.setattr(hist_mod, "get_history", _boom)
    assert client.get("/api/council/history").json()["ok"] is False


def test_setup_mock_installs_offline_fallback() -> None:
    """_setup_mock() is the disabled offline safety net — still must work."""
    from novamind.core.llm_router import LLMRouter

    names = ("generate", "generate_for_task", "_load_from_env",
             "_cooldown_provider", "_is_cooled_down")
    saved = {n: getattr(LLMRouter, n) for n in names}
    try:
        webapp._setup_mock()
        out = LLMRouter.generate(None, prompt="هذا نص", system="أنت المحلل")
        assert out["ok"] is True and out["provider"] == "mock"
        # every branch of the offline fallback must answer, never raise
        assert "أراجع الحجتين" in LLMRouter.generate(
            None, prompt="x", system="أنت الناقد")["text"]
        assert "متسقتان" in LLMRouter.generate(
            None, prompt="راجع الكود", system="أنت الناقد")["text"]
        assert "3 مخاوف" in LLMRouter.generate(
            None, prompt="x", system="أنت المحلل المتشكك")["text"]
        assert "نقص السياق" in LLMRouter.generate(
            None, prompt="راجع", system="أنت المحلل المتشكك")["text"]
        assert "الطلب مقبول" in LLMRouter.generate(
            None, prompt="x", system="أنت المحلل المدافع")["text"]
        assert "يمكن التخفيف" in LLMRouter.generate(
            None, prompt="راجع", system="أنت المحلل المدافع")["text"]
        assert LLMRouter.generate(None, prompt="p", system="")["text"].startswith("[Mock]")
        LLMRouter._load_from_env(SimpleNamespace())   # sets providers=[]
        LLMRouter._cooldown_provider(None, "n", seconds=1)
        assert LLMRouter._is_cooled_down(None, "n") is True
        assert LLMRouter.generate_for_task(None, prompt="p")["ok"] is True
    finally:
        for n, v in saved.items():
            setattr(LLMRouter, n, v)


def test_council_topic_not_found() -> None:
    body = client.post("/api/council/topic", json={"question": "__nope__"}).json()
    assert body == {"ok": False, "error": "topic not found"}


def test_council_topic_success(fake_council: _FakeBridge) -> None:
    topic_id = next(iter(topics_mod.TOPICS))
    body = client.post("/api/council/topic", json={"question": topic_id}).json()
    assert body["ok"] is True and body["topic_id"] == topic_id


def test_council_topic_bridge_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    topic_id = next(iter(topics_mod.TOPICS))
    monkeypatch.setattr(bridge_mod, "get_council_bridge",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert client.post("/api/council/topic",
                       json={"question": topic_id}).json()["ok"] is False


def test_council_history_endpoint() -> None:
    body = client.get("/api/council/history").json()
    assert body["ok"] is True and "stats" in body and "recent" in body


# ───────────────────────────── cache + metrics ─────────────────────────────

def test_cache_stats_and_clear() -> None:
    stats = client.get("/api/cache/stats").json()
    assert stats["ok"] is True and "total_entries" in stats["stats"]
    cleared = client.post("/api/cache/clear").json()
    assert cleared["ok"] is True and isinstance(cleared["cleared"], int)


def test_cache_failure_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.cache as cache_mod

    def _boom() -> Any:
        raise RuntimeError("cache down")

    monkeypatch.setattr(cache_mod, "get_cache", _boom)
    assert client.get("/api/cache/stats").json()["ok"] is False
    assert client.post("/api/cache/clear").json()["ok"] is False


def test_metrics_today_and_clear() -> None:
    today = client.get("/api/metrics/today").json()
    assert today["ok"] is True and "stats" in today
    assert client.post("/api/metrics/clear").json()["ok"] is True


def test_metrics_failure_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.nexus.monitoring as mon_mod

    def _boom() -> Any:
        raise RuntimeError("monitor down")

    monkeypatch.setattr(mon_mod, "get_monitor", _boom)
    assert client.get("/api/metrics/today").json()["ok"] is False
    assert client.post("/api/metrics/clear").json()["ok"] is False


# ───────────────────────────── routers ─────────────────────────────

def test_hybrid_run_force_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {"ok": True, "method": "m", "answer": "A",
              "trace": [{"icon": "i", "text": "t"}], "verdict": "approve",
              "score": 0.5, "transcript": [], "results": [{"agent": "a"}]}
    monkeypatch.setattr(hybrid_mod.HybridRouter, "_run_smart",
                        lambda self, p: dict(canned))
    monkeypatch.setattr(hybrid_mod.HybridRouter, "_run_loop",
                        lambda self, p: dict(canned))
    monkeypatch.setattr(hybrid_mod.HybridRouter, "_run_council",
                        lambda self, p: dict(canned))
    for force in ("code", "tool", "decision"):
        body = client.post("/api/hybrid/run",
                           json={"prompt": "any", "force": force}).json()
        assert body["ok"] is True and body["route"] == force
        assert body["answer"] == "A" and body["agents"] == ["a"]


def test_hybrid_run_classified_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hybrid_mod.HybridRouter, "_run_smart",
                        lambda self, p: {"ok": True, "method": "m", "answer": "z"})
    body = client.post("/api/hybrid/run", json={"prompt": "اكتب دالة"}).json()
    assert body["route"] == "code" and body["answer"] == "z"


def test_hybrid_run_error_returns_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(p: str) -> str:
        raise RuntimeError("classify down")

    monkeypatch.setattr(hybrid_mod, "classify", _boom)
    body = client.post("/api/hybrid/run", json={"prompt": "x"}).json()
    assert body["ok"] is False and "classify down" in body["error"]
    assert "Traceback" in body["tb"]


def test_smart_run_with_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {"ok": True,
              "decision": {"strategy": "parallel", "category": "code_generation",
                           "complexity": "complex", "risk": "low",
                           "agents": ["a", "b"], "reason": "r"},
              "results": [{"agent": "a", "ok": True, "elapsed": 0.1,
                           "result": "res" * 500, "error": "",
                           "verdict": None, "score": None}],
              "elapsed": 0.2}
    monkeypatch.setattr(sup_mod.Supervisor, "execute",
                        lambda self, p, force_strategy=None: dict(canned))
    body = client.post("/api/smart/run",
                       json={"prompt": "x", "force_strategy": "parallel"}).json()
    assert body["ok"] is True and body["decision"]["strategy"] == "parallel"
    assert body["results"][0]["result"] == "res" * 333 + "r"   # truncated to 1000


def test_smart_run_error_returns_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: Any, p: str, force_strategy: Any = None) -> dict:
        raise RuntimeError("smart down")

    monkeypatch.setattr(sup_mod.Supervisor, "execute", _boom)
    body = client.post("/api/smart/run", json={"prompt": "x"}).json()
    assert body["ok"] is False and "smart down" in body["error"]
    assert "Traceback" in body["tb"]
