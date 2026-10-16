"""Tests closing the remaining coverage gap (2026-10-16).

Covers: src/memory/knowledge_graph, src/memory/providers/{base,openai,gemini},
src/council/isolation, src/nexus/{monitoring,monitoring_patch}.
All offline / hermetic — no network, no real provider.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from src.council.isolation import IsolatedContext, IsolationManager
from src.memory.knowledge_graph import Entity, KnowledgeGraph, Relation
from src.memory.providers.base import get_provider, resolve_api_key
from src.nexus.monitoring import LLMCall, Monitor, get_monitor

# ══════════════════════════ knowledge_graph ══════════════════════════


def test_entity_relation_defaults() -> None:
    e = Entity(id="a", type="fact")
    assert e.properties == {}
    r = Relation(source="a", target="b", type="uses")
    assert r.properties == {}


def test_kg_add_and_get_entity(tmp_path: Path) -> None:
    kg = KnowledgeGraph(path=str(tmp_path / "kg.db"))
    kg.add_entity(Entity(id="n1", type="code", properties={"lang": "py"}))
    got = kg.get_entity("n1")
    assert got is not None
    assert got.type == "code"
    assert got.properties == {"lang": "py"}
    # upsert (INSERT OR REPLACE) must not raise
    kg.add_entity(Entity(id="n1", type="code", properties={"lang": "js"}))
    assert kg.get_entity("n1").properties == {"lang": "js"}  # type: ignore[union-attr]
    assert kg.get_entity("missing") is None


def test_kg_relations_and_neighbors(tmp_path: Path) -> None:
    kg = KnowledgeGraph(path=str(tmp_path / "kg.db"))
    for i in ("a", "b", "c"):
        kg.add_entity(Entity(id=i, type="n"))
    kg.add_relation(Relation(source="a", target="b", type="next"))
    kg.add_relation(Relation(source="b", target="c", type="next"))
    # duplicate relation is INSERT OR IGNORE — no raise, no double
    kg.add_relation(Relation(source="a", target="b", type="next"))

    assert set(kg.neighbors("a", depth=1)) == {"b"}
    assert set(kg.neighbors("a", depth=2)) == {"b", "c"}
    assert kg.neighbors("c", depth=1) == ["b"]  # reverse edge lookup


def test_kg_memory_db_default() -> None:
    kg = KnowledgeGraph()  # :memory:
    kg.add_entity(Entity(id="x", type="t"))
    assert kg.get_entity("x") is not None


# ══════════════════════════ providers ══════════════════════════


def test_resolve_api_key_direct_and_numbered() -> None:
    assert resolve_api_key("K", env={"K": "direct"}) == "direct"
    assert resolve_api_key("K", env={"K_2": "second"}) == "second"  # _1 missing
    assert resolve_api_key("K", env={"K_1": "first", "K_2": "second"}) == "first"
    assert resolve_api_key("K", env={}) == ""
    # max_suffix boundary: only K_3 present, max_suffix=2 → miss
    assert resolve_api_key("K", env={"K_3": "x"}, max_suffix=2) == ""


def test_get_provider_hashing() -> None:
    p = get_provider("hashing", dim=64)
    assert hasattr(p, "embed")
    assert get_provider("DEFAULT", dim=32) is not None  # case-insensitive


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ValueError, match="غير معروف"):
        get_provider("nope")


class _FakeEmbeddingsResponse:
    def __init__(self, vec: list[float]) -> None:
        self.data = [types.SimpleNamespace(embedding=vec)]


class _FakeOpenAI:
    """Duck-typed stand-in for openai.OpenAI."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.embeddings = types.SimpleNamespace(
            create=self._create
        )
        self.last_input: str | None = None

    def _create(self, model: str = "", input: str = "", **kw: object) -> _FakeEmbeddingsResponse:
        self.last_input = input
        return _FakeEmbeddingsResponse([0.1, 0.2, 0.3])


def test_openai_embeddings_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.providers.openai as mod

    monkeypatch.setattr(mod, "HAS_OPENAI", True)
    monkeypatch.setattr(mod, "OpenAI", _FakeOpenAI)
    cls = mod.OpenAIEmbeddings(api_key="sk-test")
    vec = cls.embed("hello")
    assert list(vec) == [0.1, 0.2, 0.3]
    assert cls.model == "text-embedding-3-small"
    assert cls.dim == 1536


def test_openai_embeddings_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.providers.openai as mod

    monkeypatch.setattr(mod, "HAS_OPENAI", False)
    with pytest.raises(ImportError):
        mod.OpenAIEmbeddings(api_key="sk")
    monkeypatch.setattr(mod, "HAS_OPENAI", True)
    monkeypatch.setattr(mod, "resolve_api_key", lambda *_a, **_k: "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        mod.OpenAIEmbeddings()


def test_gemini_embeddings_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.providers.gemini as mod

    monkeypatch.setattr(mod, "HAS_OPENAI", True)
    monkeypatch.setattr(mod, "OpenAI", _FakeOpenAI)
    cls = mod.GeminiEmbeddings(api_key="gk")
    assert list(cls.embed("hi")) == [0.1, 0.2, 0.3]
    # Gemini goes through the OpenAI-compatible base_url
    assert "generativelanguage.googleapis.com" in str(cls.client.base_url)
    assert cls.dim == 768


def test_gemini_embeddings_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.providers.gemini as mod

    monkeypatch.setattr(mod, "HAS_OPENAI", False)
    with pytest.raises(ImportError):
        mod.GeminiEmbeddings(api_key="gk")
    monkeypatch.setattr(mod, "HAS_OPENAI", True)
    monkeypatch.setattr(mod, "resolve_api_key", lambda *_a, **_k: "")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        mod.GeminiEmbeddings()


@pytest.mark.parametrize("provider,label", [("gemini", "Gemini"), ("openai", "OpenAI")])
def test_get_provider_wraps_import_error(
    monkeypatch: pytest.MonkeyPatch, provider: str, label: str
) -> None:
    # If the provider module fails to import, get_provider wraps the error
    import src.memory.providers.base as base

    fake = types.ModuleType(f"src.memory.providers.{provider}")

    def _getattr(attr: str) -> object:
        raise ImportError(attr)

    fake.__getattr__ = _getattr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, f"src.memory.providers.{provider}", fake)
    with pytest.raises(ImportError, match=label):
        base.get_provider(provider)


# ══════════════════════════ isolation ══════════════════════════


class _FakeMember:
    def __init__(self, name: str) -> None:
        self.name = name


def test_isolation_full_cycle() -> None:
    im = IsolationManager()
    assert im.phase == "independent"
    im.prepare([_FakeMember("a"), _FakeMember("b")], "do work")
    assert im.get_context("a") == "do work"
    assert im.all_committed() is False
    im.commit("a", "plan A")
    assert im.all_committed() is False
    im.commit("b", "plan B")
    assert im.all_committed() is True
    reveal = im.reveal_for_debate()
    assert reveal == {"a": "plan A", "b": "plan B"}
    assert im.phase == "debate"


def test_isolation_reveal_before_commit_raises() -> None:
    im = IsolationManager()
    im.prepare([_FakeMember("a")], "x")
    with pytest.raises(RuntimeError, match="العزل"):
        im.reveal_for_debate()


def test_isolated_context_defaults() -> None:
    ctx = IsolatedContext(member="m", input="i")
    assert ctx.own_response == ""
    assert ctx.committed is False


def test_isolation_prepare_resets_previous_contexts() -> None:
    im = IsolationManager()
    im.prepare([_FakeMember("old")], "1")
    im.commit("old", "r")
    im.prepare([_FakeMember("new")], "2")
    assert "old" not in im.contexts
    assert im.all_committed() is False


# ══════════════════════════ monitoring ══════════════════════════


def test_monitor_log_and_session_stats(tmp_path: Path) -> None:
    mon = Monitor(log_dir=str(tmp_path))
    call = mon.log_call(
        provider="groq", model="m", elapsed=1.5, ok=True,
        prompt="hello world this is a prompt",
        response="and a response here", task_type="chat", caller="test",
    )
    assert isinstance(call, LLMCall)
    assert call.tokens_in >= 1 and call.tokens_out >= 1
    assert call.cost_usd > 0
    st = mon.get_session_stats()
    assert st["total_calls"] == 1
    assert st["successes"] == 1
    assert st["success_rate"] == 100.0
    assert st["by_provider"]["groq"]["calls"] == 1
    assert st["avg_time_s"] == 1.5


def test_monitor_today_file_roundtrip_and_clear(tmp_path: Path) -> None:
    mon = Monitor(log_dir=str(tmp_path))
    mon.log_call(provider="gemini", model="m", elapsed=0.1, ok=False, error="boom" * 100)
    today = mon.get_today_stats()
    assert today["total_calls"] == 1
    assert today["failures"] == 1
    # error is truncated to 200 chars
    assert mon._session_calls[0].error == "boom" * 50
    # persisted as JSONL, one line
    lines = (tmp_path / Path(mon._today_file).name).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ok"] is False
    assert mon.clear_today() == 1
    assert mon.clear_today() == 0
    assert mon.get_today_stats()["total_calls"] == 0


def test_monitor_empty_stats_and_estimates(tmp_path: Path) -> None:
    mon = Monitor(log_dir=str(tmp_path))
    empty = mon.get_today_stats()
    assert empty["total_calls"] == 0
    assert mon.get_session_stats()["total_calls"] == 0
    assert mon._estimate_tokens("") == 0
    assert mon._estimate_tokens("abcd") == 1
    # unknown provider → default rates
    assert mon._estimate_cost("mystery", 1_000_000, 1_000_000) == pytest.approx(0.30)
    assert mon._estimate_cost("groq_01", 1_000_000, 0) == pytest.approx(0.05)


def test_monitor_corrupt_today_file_is_tolerated(tmp_path: Path) -> None:
    mon = Monitor(log_dir=str(tmp_path))
    (tmp_path / Path(mon._today_file).name).write_text("{bad json\n", encoding="utf-8")
    assert mon.get_today_stats()["total_calls"] == 0


def test_get_monitor_singleton() -> None:
    a = get_monitor()
    b = get_monitor()
    assert a is b


# ══════════════════════════ monitoring_patch ══════════════════════════

_PATCH_PATH = Path(__file__).resolve().parents[1] / "src" / "nexus" / "monitoring_patch.py"


def _load_fresh_patch(monkeypatch: pytest.MonkeyPatch, router_cls: type) -> types.ModuleType:
    """Load monitoring_patch under a unique name with a FAKE LLMRouter.

    Never touches the real novamind.core.llm_router (the module-level
    patch would otherwise permanently wrap the production class).
    """
    fake_mod = types.ModuleType("novamind.core.llm_router")
    fake_mod.LLMRouter = router_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", fake_mod)
    spec = importlib.util.spec_from_file_location(
        "monitoring_patch_under_test", _PATCH_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_patch_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.nexus.monitoring as mon_mod

    monkeypatch.setattr(mon_mod, "_monitor", Monitor(log_dir=str(tmp_path)))

    class R:
        def generate(self, prompt: str = "", system: str = "", provider: str | None = None, **kw: object) -> dict:
            return {"provider": "p", "model": "m", "text": "t", "ok": True}

    mod = _load_fresh_patch(monkeypatch, R)
    assert mod._patched is True
    wrapped = R.generate
    # second explicit call is a no-op that returns True
    assert mod.patch_llm_router() is True
    assert R.generate is wrapped  # not double-wrapped


def test_patch_logs_successful_dict_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.nexus.monitoring as mon_mod

    monkeypatch.setattr(mon_mod, "_monitor", Monitor(log_dir=str(tmp_path)))

    class R:
        def generate(self, prompt: str = "", system: str = "", provider: str | None = None, **kw: object) -> dict:
            return {"provider": "groq", "model": "qwen", "text": "answer", "ok": True}

    _load_fresh_patch(monkeypatch, R)
    r = R()
    out = r.generate(prompt="hi", system="sys", provider="x")
    assert out["ok"] is True
    st = mon_mod.get_monitor().get_session_stats()
    assert st["total_calls"] == 1
    assert st["by_provider"]["groq"]["calls"] == 1


def test_patch_handles_non_dict_and_none_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.nexus.monitoring as mon_mod

    monkeypatch.setattr(mon_mod, "_monitor", Monitor(log_dir=str(tmp_path)))

    class R:
        def generate(self, prompt: str = "", system: str = "", provider: str | None = None, **kw: object) -> str:
            return "plain text"  # not a dict → provider unknown, ok=True

    _load_fresh_patch(monkeypatch, R)
    assert R().generate(prompt="p") == "plain text"

    class R2:
        def generate(self, prompt: str = "", system: str = "", provider: str | None = None, **kw: object) -> dict:
            return {"provider": None, "model": None, "text": None, "ok": False}

    _load_fresh_patch(monkeypatch, R2)
    R2().generate()
    st = mon_mod.get_monitor().get_session_stats()
    assert st["total_calls"] == 2
    assert st["failures"] == 1
    assert "unknown" in st["by_provider"]


def test_patch_logs_failure_and_reraises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.nexus.monitoring as mon_mod

    monkeypatch.setattr(mon_mod, "_monitor", Monitor(log_dir=str(tmp_path)))

    class R:
        def generate(self, prompt: str = "", system: str = "", provider: str | None = None, **kw: object) -> dict:
            raise RuntimeError("provider down")

    _load_fresh_patch(monkeypatch, R)
    with pytest.raises(RuntimeError, match="provider down"):
        R().generate(prompt="x", provider="groq")
    st = mon_mod.get_monitor().get_session_stats()
    assert st["total_calls"] == 1
    assert st["failures"] == 1
    assert st["by_provider"]["groq"]["calls"] == 1


def test_patch_import_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # LLMRouter attribute missing → ImportError branch → False (never raises)
    broken = types.ModuleType("novamind.core.llm_router")  # no LLMRouter attr
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", broken)
    spec = importlib.util.spec_from_file_location(
        "monitoring_patch_broken_test", _PATCH_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._patched is False
    assert mod.patch_llm_router() is False
