"""Tests closing RAG/memory-layer + sysinfo + cache coverage gaps (2026-10-16).

Covers: src/memory/{rag_engine,agent_rag_bridge,vector_store}, src/core/sysinfo,
src/council/rag_bridge (offline: fake LLM + fake rag + fake cache/history).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest

from src.council.cache import CACHE_VERSION, CachedVerdict, CouncilCache
from src.council.engine import CouncilResult
from src.memory.embeddings import HashingEmbedder
from src.memory.rag_engine import RAGEngine
from src.memory.vector_store import SQLiteVecStore
from src.memory.vector_store.base import SearchResult, VectorStore
from src.memory.vector_store.sqlite_vec_store import _embedding_to_blob


# ══════════════════════════ vector store ══════════════════════════


def test_embedding_to_blob_roundtrip() -> None:
    blob = _embedding_to_blob([1.0, 2.0, 3.0])
    assert len(blob) == 12  # 3 × float32


def test_sqlite_vec_store_crud(tmp_path: Path) -> None:
    store = SQLiteVecStore(str(tmp_path / "v.db"), dim=4)
    assert isinstance(store, VectorStore)
    store.add("d1", "alpha", [1.0, 0.0, 0.0, 0.0], {"lang": "en"})
    store.add("d2", "beta", [0.0, 1.0, 0.0, 0.0])
    results = store.search([1.0, 0.0, 0.0, 0.0], k=2)
    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].id == "d1"  # nearest first
    assert results[0].metadata == {"lang": "en"}
    assert store.delete("d1") is True
    assert store.delete("nope") is False
    assert [r.id for r in store.search([1.0, 0.0, 0.0, 0.0], k=2)] == ["d2"]
    store.clear()
    assert store.search([1.0, 0.0, 0.0, 0.0], k=2) == []
    store.close()


def test_sqlite_vec_store_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "v.db"
    store = SQLiteVecStore(str(nested), dim=4)
    assert nested.parent.is_dir()
    store.close()


def test_sqlite_vec_missing_extension_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubConn:
        def enable_load_extension(self, _v: bool) -> None:
            pass

        def load_extension(self, _name: str) -> None:
            raise sqlite3.OperationalError("no such extension")

    monkeypatch.setattr(sqlite3, "connect", lambda _p: StubConn())
    with pytest.raises(RuntimeError, match="sqlite-vec"):
        SQLiteVecStore(str(tmp_path / "x.db"), dim=4)


# ══════════════════════════ rag engine ══════════════════════════

def _rag_engine(tmp_path: Path, **kw: Any) -> RAGEngine:
    """RAGEngine whose embedder dimension MATCHES the store dimension."""
    return RAGEngine(
        vector_store_path=str(tmp_path / "rag.db"),
        embedder=HashingEmbedder(dim=64), dim=64, **kw,
    )



def test_rag_engine_add_retrieve_roundtrip(tmp_path: Path) -> None:
    eng = _rag_engine(tmp_path)
    eng.add_document("doc1", "python is a programming language")
    eng.add_document("doc2", "cairo is the capital of egypt")
    hits = eng.retrieve("programming language", k=1)
    assert hits and hits[0].id == "doc1"
    # generate without llm → local-rag envelope with the context inline
    out = eng.generate("programming language", k=1)
    assert out["ok"] is True
    assert out["provider"] == "local-rag"
    assert "doc1" in out["text"]
    eng.close()


def test_rag_engine_add_documents_counts_valid_tuples(tmp_path: Path) -> None:
    eng = _rag_engine(tmp_path)
    n = eng.add_documents([
        ("a", "first doc"),
        ("b", "second doc"),
        "not-a-tuple",          # ignored
        ("c",),                 # too short — ignored
    ])
    assert n == 2
    assert len(eng.retrieve("first", k=5)) >= 1
    eng.close()


def test_rag_engine_empty_generate(tmp_path: Path) -> None:
    eng = _rag_engine(tmp_path)
    out = eng.generate("nothing stored yet", k=3)
    assert "[RAG Context]\n\n\n[Query]" in out["text"]
    eng.close()


def test_rag_engine_with_llm_router(tmp_path: Path) -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def generate_for_task(self, **kw: Any) -> dict:
            self.kwargs = kw
            return {"ok": True, "text": "answer"}

    fake = FakeLLM()
    eng = _rag_engine(tmp_path, llm_router=fake)
    out = eng.generate("q", k=2, temperature=0.1)
    assert out == {"ok": True, "text": "answer"}
    assert fake.kwargs["task_type"] == "analysis"
    assert fake.kwargs["system"]  # system prompt built
    eng.close()


def test_rag_engine_default_path_is_under_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # redirect $HOME so the default path lands in tmp, never the real ~/.nexus
    monkeypatch.setattr(os.path, "expanduser", lambda _p: str(tmp_path))
    eng = RAGEngine(dim=8)
    assert eng.vector_store_path == str(tmp_path / ".nexus" / "data" / "vectors.db")
    assert eng.dim == 8  # dim taken from the explicit arg
    eng.close()


# ══════════════════════════ agent rag bridge ══════════════════════════


def _fresh_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import src.memory.agent_rag_bridge as arb
    from src.memory.embedding_config import ResolvedEmbedder
    from src.memory.embeddings import HashingEmbedder

    emb = HashingEmbedder(dim=64)
    resolved = ResolvedEmbedder(
        spec="hashing", embedder=emb, dim=64,
        path=str(tmp_path / "vectors.db"), fallback_reason=None,
    )
    monkeypatch.setattr(
        "src.memory.embedding_config.resolve_rag",
        lambda *_a, **_k: resolved,
    )
    monkeypatch.setattr(arb.AgentRAGBridge, "_instance", None)
    monkeypatch.setattr(arb, "_bridge", None)
    return arb.AgentRAGBridge()


def test_agent_rag_bridge_singleton_and_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b1 = _fresh_bridge(tmp_path, monkeypatch)
    b2 = b1.__class__()
    assert b1 is b2  # singleton
    assert b1.embedding_spec == "hashing"
    assert b1.embedding_fallback is None
    doc_id = b1.remember("the queen coordinates the combs")
    assert doc_id.startswith("mem_")
    hits = b1.recall("queen coordinates", k=1)
    assert hits
    enriched = b1.enrich_prompt("tell me about the queen", k=1)
    assert "سياق من الذاكرة" in enriched


def test_agent_rag_bridge_enrich_without_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _fresh_bridge(tmp_path, monkeypatch)
    assert b.enrich_prompt("unrelated question xyz") == "unrelated question xyz"


def test_agent_rag_bridge_enrich_swallows_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _fresh_bridge(tmp_path, monkeypatch)

    class Boom:
        def retrieve(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("store down")

    monkeypatch.setattr(b, "rag", Boom())
    assert b.enrich_prompt("anything") == "anything"


def test_get_bridge_singleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.agent_rag_bridge as arb

    _fresh_bridge(tmp_path, monkeypatch)  # resets module _bridge too
    b = arb.get_bridge()
    assert arb.get_bridge() is b


def test_agent_rag_bridge_fallback_prints_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.memory.agent_rag_bridge as arb
    from src.memory.embedding_config import ResolvedEmbedder
    from src.memory.embeddings import HashingEmbedder

    resolved = ResolvedEmbedder(
        spec="hashing", embedder=HashingEmbedder(dim=64), dim=64,
        path=str(tmp_path / "v.db"), fallback_reason="gemini غير متاح — رجعنا إلى hashing",
    )
    monkeypatch.setattr(
        "src.memory.embedding_config.resolve_rag", lambda *_a, **_k: resolved
    )
    monkeypatch.setattr(arb.AgentRAGBridge, "_instance", None)
    b = arb.AgentRAGBridge()
    assert "[RAG]" in capsys.readouterr().out
    assert b.embedding_fallback is not None


# ══════════════════════════ council rag bridge ══════════════════════════


class _Doc:
    def __init__(self, text: str, distance: float = 0.1) -> None:
        self.text = text
        self.distance = distance


class FakeRag:
    def __init__(self, docs: list[Any] | None = None, raises: bool = False) -> None:
        self.docs = docs or []
        self.raises = raises
        self.remembered: list[tuple[str, str]] = []

    def recall(self, _q: str, k: int = 5) -> list[Any]:
        if self.raises:
            raise RuntimeError("rag down")
        return self.docs[:k]

    def remember(self, summary: str, doc_id: str = "") -> None:
        self.remembered.append((summary, doc_id))

    @property
    def embedding_spec(self) -> str:
        return "hashing"

    @property
    def embedding_fallback(self) -> None:
        return None


class FakeLLMRouter:
    def __init__(self, replies: list[dict] | None = None) -> None:
        self.replies = list(replies or [])

    def generate(self, **_kw: Any) -> Any:
        if self.replies:
            return self.replies.pop(0)
        return {"ok": True, "text": "[الحكم: موافق]\n[التوصية: نعم]"}


class FakeEngine:
    """Stand-in for CouncilEngine — records calls, returns a canned result."""

    def __init__(self, result: CouncilResult | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result or CouncilResult(
            verdict="approve", score=0.85, consensus=True, rounds=0,
            transcript=[{"member": "analyst", "response": "ok"}],
            elapsed=0.01, security_events=[],
        )

    def deliberate(self, question: str, context: str = "",
                   on_event: Any = None) -> CouncilResult:
        self.calls.append({"question": question, "context": context})
        if on_event:
            on_event("phase", {"name": "independent"})
        return self.result


class FakeCache:
    def __init__(self, hit: CachedVerdict | None = None) -> None:
        self.hit = hit
        self.stored: list[str] = []

    def get(self, _q: str) -> CachedVerdict | None:
        return self.hit

    def set(self, question: str, _result: Any) -> str:
        self.stored.append(question)
        return "hash"


class FakeHistory:
    def __init__(self, records: list[dict] | None = None) -> None:
        self.records = records or []
        self.saved: list[str] = []

    def list_recent(self, n: int = 10) -> list[dict]:
        return self.records[:n]

    def save(self, _result: Any, category: str = "", query: str = "") -> str:
        self.saved.append(query)
        return "decision_test_1"


def _bridge(
    monkeypatch: pytest.MonkeyPatch,
    rag: Any = None,
    llm_replies: list[dict] | None = None,
) -> Any:
    import src.council.rag_bridge as rb
    import src.council.history as hist_mod
    import src.council.cache as cache_mod

    # keep the heavy real LLMRouter out of these tests
    fake_mod = types.ModuleType("novamind.core.llm_router")
    fake_mod.LLMRouter = FakeLLMRouter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", fake_mod)

    bridge = rb.CouncilRAGBridge(rag_bridge=rag or FakeRag())
    fake_engine = FakeEngine()
    bridge.engine = fake_engine
    bridge._fake_engine = fake_engine  # type: ignore[attr-defined]
    monkeypatch.setattr(hist_mod, "get_history", lambda: FakeHistory())
    monkeypatch.setattr(cache_mod, "get_cache", lambda: FakeCache())
    if llm_replies is not None:
        bridge.engine.llm = FakeLLMRouter(llm_replies)  # type: ignore[union-attr]
    return bridge


def test_rag_bridge_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.rag_bridge as rb

    fake_mod = types.ModuleType("novamind.core.llm_router")
    fake_mod.LLMRouter = FakeLLMRouter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", fake_mod)
    bridge = rb.CouncilRAGBridge(rag_bridge=FakeRag())
    assert bridge.embedding_spec == "hashing"
    assert bridge.embedding_fallback is None


def test_deliberate_with_memory_augments_context(monkeypatch: pytest.MonkeyPatch) -> None:
    rag = FakeRag(docs=[
        _Doc("[Council DECIDE] old council answer"),   # echo → filtered
        _Doc("قاعدة بيانات sqlite سريعة", distance=0.2),
        _Doc("بعيدة جداً", distance=5.0),              # beyond threshold → filtered
    ])
    bridge = _bridge(monkeypatch, rag=rag)
    res = bridge.deliberate_with_memory("سؤال جديد")
    ctx = bridge._fake_engine.calls[0]["context"]  # type: ignore[attr-defined]
    assert "sqlite" in ctx
    assert "[Council" not in ctx  # council echoes filtered out
    assert "بعيدة جداً" not in ctx
    assert isinstance(res, CouncilResult)


def test_deliberate_with_memory_rag_error_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(monkeypatch, rag=FakeRag(raises=True))
    res = bridge.deliberate_with_memory("أي سؤال")
    assert res.verdict == "approve"
    assert bridge._fake_engine.calls  # type: ignore[attr-defined]


def test_deliberate_with_memory_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.cache as cache_mod

    cached = CachedVerdict(
        question_hash="h", question="q", verdict="reject", score=0.2,
        rounds=1, transcript_summary="[analyst]: no", timestamp=time.time(),
        expires_at=time.time() + 60, transcript=[{"member": "analyst"}],
        consensus=False, cache_version=CACHE_VERSION, hits=2,
    )
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(cache_mod, "get_cache", lambda: FakeCache(hit=cached))
    res = bridge.deliberate_with_memory("q")
    assert res.verdict == "reject"
    assert res.rounds == 1
    assert res.transcript == [{"member": "analyst"}]
    assert not bridge._fake_engine.calls  # type: ignore[attr-defined]  # engine skipped


def test_deliberate_with_memory_skips_cache_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(monkeypatch)
    res = bridge.deliberate_with_memory("q", context="some context", use_cache=True)
    assert bridge._fake_engine.calls  # type: ignore[attr-defined]  # cache bypassed
    assert res.verdict == "approve"


def test_deliberate_with_memory_past_hint_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.council.history as hist_mod

    records = [{"id": "r1", "query": "استخدام قاعدة بيانات sqlite للمشروع",
                "verdict": "approve", "score": 0.9}]
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(hist_mod, "get_history", lambda: FakeHistory(records))
    bridge.deliberate_with_memory("هل نستخدم قاعدة بيانات sqlite؟")
    ctx = bridge._fake_engine.calls[0]["context"]  # type: ignore[attr-defined]
    assert "قرارات سابقة مشابهة" in ctx
    assert "APPROVE" in ctx


def test_deliberate_with_memory_past_hint_too_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(monkeypatch)
    bridge.deliberate_with_memory("نعم")  # all stopwords → no hint
    assert bridge._fake_engine.calls[0]["context"] == ""  # type: ignore[attr-defined]


def test_deliberate_with_memory_saves_history_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.council.cache as cache_mod
    import src.council.history as hist_mod

    hist = FakeHistory()
    cache = FakeCache()
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(hist_mod, "get_history", lambda: hist)
    monkeypatch.setattr(cache_mod, "get_cache", lambda: cache)
    res = bridge.deliberate_with_memory("احفظ النتيجة")
    assert hist.saved == ["احفظ النتيجة"]
    assert getattr(res, "_record_id") == "decision_test_1"
    assert cache.stored == ["احفظ النتيجة"]


def test_deliberate_with_memory_history_error_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.council.history as hist_mod

    def _boom() -> Any:
        raise RuntimeError("history down")

    monkeypatch.setattr(hist_mod, "get_history", _boom)
    bridge = _bridge(monkeypatch)
    res = bridge.deliberate_with_memory("q")
    assert res.verdict == "approve"  # flow continued


def test_deliberate_streaming_forwards_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, Any]] = []
    bridge = _bridge(monkeypatch)
    res = bridge.deliberate_streaming("بث مباشر", on_event=lambda e, p: events.append((e, p)))
    assert res.verdict == "approve"
    assert ("phase", {"name": "independent"}) in events


def test_deliberate_streaming_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.cache as cache_mod

    cached = CachedVerdict(
        question_hash="h", question="q", verdict="approve", score=0.9,
        rounds=0, transcript_summary="s", timestamp=time.time(),
        expires_at=time.time() + 60, transcript=None, consensus=None,
        cache_version=CACHE_VERSION, hits=7,
    )
    events: list[tuple[str, Any]] = []
    bridge = _bridge(monkeypatch)
    monkeypatch.setattr(cache_mod, "get_cache", lambda: FakeCache(hit=cached))
    res = bridge.deliberate_streaming("q", on_event=lambda e, p: events.append((e, p)))
    assert res.verdict == "approve"
    # consensus=None + score 0.9 ≥ 0.7 → True
    assert res.consensus is True
    assert res.transcript == [{"phase": "cached", "member": "cache", "response": "s"}]
    assert any(e == "status" for e, _ in events)
    assert not bridge._fake_engine.calls  # type: ignore[attr-defined]


def test_deliberate_streaming_rag_and_history_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.council.cache as cache_mod
    import src.council.history as hist_mod

    rag = FakeRag(docs=[_Doc("ذاكرة مفيدة", distance=0.1)])
    hist = FakeHistory(records=[{
        "id": "r1", "query": "حماية قاعدة بيانات sqlite",
        "verdict": "reject", "score": 0.4,
    }])
    cache = FakeCache()
    bridge = _bridge(monkeypatch, rag=rag)
    monkeypatch.setattr(hist_mod, "get_history", lambda: hist)
    monkeypatch.setattr(cache_mod, "get_cache", lambda: cache)
    events: list[tuple[str, Any]] = []
    res = bridge.deliberate_streaming(
        "هل نستخدم قاعدة بيانات sqlite؟",
        on_event=lambda e, p: events.append((e, p)),
    )
    assert res.verdict == "approve"
    statuses = [p.get("phase") for e, p in events if e == "status"]
    assert "memory" in statuses
    assert "past" in statuses
    assert any(e == "log" for e, _ in events)  # history save notice
    assert cache.stored  # cache set ran
    ctx = bridge._fake_engine.calls[0]["context"]  # type: ignore[attr-defined]
    assert "ذاكرة مفيدة" in ctx


def test_deliberate_streaming_on_event_exception_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bad(_e: str, _p: Any) -> None:
        raise RuntimeError("listener broke")

    bridge = _bridge(monkeypatch)
    res = bridge.deliberate_streaming("q", on_event=_bad)
    assert res.verdict == "approve"


def test_get_council_bridge_is_process_singleton() -> None:
    import src.council.rag_bridge as rb

    try:
        a = rb.get_council_bridge()
        assert rb.get_council_bridge() is a
    finally:
        rb._bridge = None  # never leave the heavy singleton for other tests


# ══════════════════════════ cache edge cases ══════════════════════════


def test_cache_get_corrupt_file(tmp_path: Path) -> None:
    c = CouncilCache(cache_dir=str(tmp_path))
    h = c._hash_question("q")
    (tmp_path / f"{h}.json").write_text("{bad", encoding="utf-8")
    assert c.get("q") is None


def test_cache_get_stale_version(tmp_path: Path) -> None:
    c = CouncilCache(cache_dir=str(tmp_path))
    c.set("q", types.SimpleNamespace(
        verdict="approve", score=0.9, rounds=0,
        transcript=[{"member": "a", "response": "r"}], consensus=True,
    ))
    import json
    path = tmp_path / f"{c._hash_question('q')}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cache_version"] = "v0-ancient"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert c.get("q") is None


def test_cache_stats_expired_and_corrupt(tmp_path: Path) -> None:
    c = CouncilCache(cache_dir=str(tmp_path))
    c.set("fresh", types.SimpleNamespace(
        verdict="approve", score=0.9, rounds=0,
        transcript=[], consensus=True,
    ))
    # expired entry
    old = CachedVerdict(
        question_hash="old", question="old", verdict="reject", score=0.1,
        rounds=1, transcript_summary="", timestamp=0, expires_at=1,
        cache_version=CACHE_VERSION,
    )
    import json
    from dataclasses import asdict
    (tmp_path / "old.json").write_text(json.dumps(asdict(old)), encoding="utf-8")
    (tmp_path / "corrupt.json").write_text("not json", encoding="utf-8")
    st = c.stats()
    assert st["total_entries"] == 3
    assert st["expired_entries"] == 1
    assert st["valid_entries"] == 1
    assert c.clear() == 3


def test_cache_set_tolerates_broken_result(tmp_path: Path) -> None:
    c = CouncilCache(cache_dir=str(tmp_path))

    class Weird:
        verdict = "approve"
        score = 0.5
        rounds = 1

        @property
        def transcript(self) -> Any:
            raise RuntimeError("no transcript")

    qh = c.set("سؤال بلا transcript", Weird())
    assert qh and c.get("سؤال بلا transcript") is not None


# ══════════════════════════ sysinfo ══════════════════════════


@pytest.fixture()
def fake_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import src.core.sysinfo as si

    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal:       8000000 kB\n"
        "MemAvailable:   2000000 kB\n"
        "MemFree:        1000000 kB\n"
        "MalformedLineNoColon\n",
        encoding="utf-8",
    )
    (proc / "uptime").write_text("12345.67 0 0\n", encoding="utf-8")
    monkeypatch.setattr(si, "_PROC", proc)
    return proc


def test_sysinfo_memory_uptime_cpu(fake_proc: Path) -> None:
    import src.core.sysinfo as si

    mem = si.memory()
    assert mem["total_kb"] == 8000000
    assert mem["available_kb"] == 2000000
    assert mem["used_kb"] == 6000000
    assert mem["used_percent"] == 75.0
    assert si.uptime() == pytest.approx(12345.67)
    assert si.cpu_count() >= 1
    la = si.load_average()
    assert la is None or len(la) == 3


def test_sysinfo_battery_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.core.sysinfo as si

    power = tmp_path / "power"
    (power / "BAT0").mkdir(parents=True)
    (power / "BAT0" / "capacity").write_text("55\n", encoding="utf-8")
    (power / "BAT0" / "status").write_text("Discharging\n", encoding="utf-8")
    # a supply without capacity → skipped; one with bad capacity → skipped
    (power / "usb").mkdir()
    (power / "AC").mkdir()
    (power / "AC" / "capacity").write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(si, "_POWER", power)
    bat = si.battery()
    assert bat == {"percent": 55, "status": "Discharging", "name": "BAT0"}


def test_sysinfo_battery_absent_and_snapshot(
    fake_proc: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import src.core.sysinfo as si

    monkeypatch.setattr(si, "_POWER", tmp_path / "no-power-dir")
    assert si.battery() is None
    snap = si.snapshot()
    assert snap["cpu_count"] >= 1
    assert snap["memory"]["total_kb"] == 8000000
    assert snap["uptime"] == pytest.approx(12345.67)
    assert snap["battery"] is None


def test_sysinfo_missing_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.core.sysinfo as si

    monkeypatch.setattr(si, "_PROC", tmp_path / "empty-proc")
    assert si.memory() == {}
    assert si.uptime() == 0.0


def test_sysinfo_malformed_uptime(monkeypatch: pytest.MonkeyPatch, fake_proc: Path) -> None:
    import src.core.sysinfo as si

    (fake_proc / "uptime").write_text("not-a-float\n", encoding="utf-8")
    assert si.uptime() == 0.0
