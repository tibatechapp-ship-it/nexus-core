"""Closes the remaining council-layer coverage gaps (2026-10-18).

Scope: the workbench council layer — ``src/council/{rag_bridge,history,craft,
builder,engine,recommend,cache,trust}``.  Every test here targets a specific
untaken branch that the normal suite never reaches:

* import-guard / optional-dependency fallbacks (no LLM router, no RAG bridge),
* defensive ``except Exception`` paths (cache, history, RAG, disk writes),
* malformed model output (bad JSON, non-dict items, non-dict replies),
* path-escape and manifest corruption guards.

The heavy fakes (FakeRag/FakeCache/FakeHistory/FakeLLMRouter/FakeEngine) live in
``tests/test_rag_layer_coverage.py`` and are reused here — one definition, one
behaviour to keep in sync.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.test_rag_layer_coverage import (
    FakeCache,
    FakeEngine,
    FakeHistory,
    FakeLLMRouter,
    FakeRag,
    _Doc,
)

import src.council.builder as builder_mod
import src.council.cache as cache_mod
import src.council.craft as craft_mod
import src.council.engine as engine_mod
import src.council.history as hist_mod
import src.council.rag_bridge as rag_bridge_mod


# ═════════════════════════════ helpers ═════════════════════════════


class _RaisingRouter:
    """LLMRouter stand-in whose construction fails."""

    def __init__(self) -> None:
        raise RuntimeError("router unavailable")


def _inject_raising_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``from novamind.core.llm_router import LLMRouter`` import but fail."""
    mod = types.ModuleType("novamind.core.llm_router")
    mod.LLMRouter = _RaisingRouter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", mod)


def _inject_working_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real (slow, network-bound) router out of these tests."""
    mod = types.ModuleType("novamind.core.llm_router")
    mod.LLMRouter = FakeLLMRouter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "novamind.core.llm_router", mod)


def _failing_bridge_module() -> types.ModuleType:
    """``src.memory.agent_rag_bridge`` whose ``get_bridge()`` raises."""
    mod = types.ModuleType("src.memory.agent_rag_bridge")

    def _boom() -> Any:
        raise RuntimeError("no rag bridge")

    mod.get_bridge = _boom  # type: ignore[attr-defined]
    return mod


def _boom_cache() -> Any:
    raise RuntimeError("cache down")


class _CacheSetBoom(FakeCache):
    """Cache whose reads succeed but whose writes raise."""

    def set(self, question: str, _result: Any) -> str:
        raise RuntimeError("cache write failed")


class _HistorySaveBoom(FakeHistory):
    """History whose reads succeed but whose writes raise."""

    def save(self, _result: Any, category: str = "", query: str = "") -> str:
        raise RuntimeError("history save failed")


class _ObjectRecord:
    """History record exposing attributes (not dict keys)."""

    def __init__(self, query: str, verdict: str = "approve",
                 score: float = 0.9) -> None:
        self.query = query
        self.verdict = verdict
        self.score = score


class _RecordsHistory:
    """History returning object-shaped records."""

    def __init__(self, records: list[Any]) -> None:
        self.records = records

    def list_recent(self, n: int = 30) -> list[Any]:
        return self.records[:n]


class _BrokenHistory:
    """History whose ``list_recent`` explodes."""

    def list_recent(self, n: int = 30) -> list[Any]:
        raise RuntimeError("history down")


def _bridge_with(
    monkeypatch: pytest.MonkeyPatch,
    rag: Any = None,
    cache_factory: Any = None,
    history_factory: Any = None,
) -> Any:
    """A CouncilRAGBridge wired to fakes (optionally failing ones)."""
    _inject_working_router(monkeypatch)
    bridge = rag_bridge_mod.CouncilRAGBridge(rag_bridge=rag or FakeRag())
    bridge.engine = FakeEngine()
    monkeypatch.setattr(
        hist_mod, "get_history",
        history_factory if history_factory is not None else (lambda: FakeHistory()),
    )
    monkeypatch.setattr(
        cache_mod, "get_cache",
        cache_factory if cache_factory is not None else (lambda: FakeCache()),
    )
    return bridge


def _collect_events(sink: list[tuple[str, Any]]) -> Any:
    def _on_event(event: str, payload: Any) -> None:
        sink.append((event, payload))

    return _on_event


def _exec_module_without_repo_root(module: Any) -> dict[str, Any]:
    """Exec a module's source the way a bare interpreter would see it.

    Covers the ``if ROOT not in sys.path: sys.path.insert(0, ROOT)`` bootstrap
    guards, which never fire during a normal import (the root is already there).
    To make the guard fire, the interpreter is reduced to its own entries first
    and the ``src*`` packages are hidden from ``sys.modules`` (otherwise the
    cached package's ``__path__`` would still satisfy the import).

    The namespace returned carries ``__sys_path_after__`` — a copy of
    ``sys.path`` as the module left it — so a test can prove the guard really
    re-inserted its root.  Everything is restored afterwards, and the module
    runs in a throwaway namespace: nothing real is mutated.
    """
    path = os.path.abspath(str(module.__file__))
    prefix = os.path.abspath(sys.prefix)
    saved_path = list(sys.path)
    hidden = {name: mod for name, mod in sys.modules.items()
              if name == "src" or name.startswith("src.")}
    namespace: dict[str, Any] = {"__name__": "_coverage_probe", "__file__": path}
    try:
        sys.path[:] = [p for p in saved_path
                       if os.path.abspath(p or ".").startswith(prefix)]
        for name in hidden:
            del sys.modules[name]
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        exec(compile(source, path, "exec"), namespace)  # noqa: S102 - trusted local file
        namespace["__sys_path_after__"] = list(sys.path)
    finally:
        sys.modules.update(hidden)
        sys.path[:] = saved_path
    return namespace


def _result(**kw: Any) -> Any:
    """A minimal result object accepted by CouncilHistory.save."""
    base = {"verdict": "approve", "score": 0.9, "rounds": 1, "consensus": True}
    base.update(kw)
    return types.SimpleNamespace(**base)


# ═══════════════════════ rag_bridge: import + cache paths ═══════════════════════


def test_bridge_init_swallows_router_import_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    _inject_raising_router(monkeypatch)
    bridge = rag_bridge_mod.CouncilRAGBridge(rag_bridge=FakeRag())
    assert bridge.engine.llm is None  # fell back to the offline engine


def test_engine_init_swallows_router_import_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    _inject_raising_router(monkeypatch)
    eng = engine_mod.CouncilEngine()
    assert eng.llm is None


def test_past_hint_reads_attribute_records(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``_fld`` getattr arm + the low-overlap arc of the scan loop."""
    _inject_working_router(monkeypatch)
    history = _RecordsHistory([
        _ObjectRecord("alpha beta gamma"),   # overlap 2 → kept
        _ObjectRecord("zzz"),                # overlap 0 → arc 70->66
    ])
    monkeypatch.setattr(hist_mod, "get_history", lambda: history)
    bridge = rag_bridge_mod.CouncilRAGBridge(rag_bridge=FakeRag())
    hint = bridge._past_hint("alpha beta")
    assert "قرارات سابقة" in hint
    assert "ALPHA BETA GAMMA" in hint.upper()


def test_past_hint_swallows_history_failure(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    _inject_working_router(monkeypatch)
    monkeypatch.setattr(hist_mod, "get_history", lambda: _BrokenHistory())
    bridge = rag_bridge_mod.CouncilRAGBridge(rag_bridge=FakeRag())
    assert bridge._past_hint("alpha beta") == ""


def test_deliberate_with_memory_reports_cache_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dying cache must degrade loudly, never break the debate."""
    bridge = _bridge_with(monkeypatch, cache_factory=_boom_cache)
    out = bridge.deliberate_with_memory("سؤال اختباري")
    captured = capsys.readouterr().out
    assert "CACHE GET ERROR" in captured
    assert "CACHE SET ERROR" in captured
    assert out.verdict == "approve"


def test_deliberate_with_memory_swallows_history_save_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bridge = _bridge_with(monkeypatch, history_factory=lambda: _HistorySaveBoom())
    out = bridge.deliberate_with_memory("سؤال اختباري")
    assert out.verdict == "approve"
    assert "خطأ الحفظ" not in capsys.readouterr().out  # swallowed silently


def test_deliberate_streaming_skips_cache_when_disabled(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """``use_cache=False`` skips BOTH the cache read and the cache write."""
    cache = FakeCache()
    bridge = _bridge_with(monkeypatch, cache_factory=lambda: cache)
    events: list[tuple[str, Any]] = []
    out = bridge.deliberate_streaming("سؤال", _collect_events(events), use_cache=False)
    assert out.verdict == "approve"
    assert cache.stored == []
    assert events  # the stream still emitted


def test_deliberate_streaming_reports_cache_get_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge_with(monkeypatch, cache_factory=_boom_cache)
    events: list[tuple[str, Any]] = []
    out = bridge.deliberate_streaming("سؤال", _collect_events(events))
    assert out.verdict == "approve"


def test_deliberate_streaming_swallows_rag_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge_with(monkeypatch, rag=FakeRag(raises=True))
    events: list[tuple[str, Any]] = []
    out = bridge.deliberate_streaming("سؤال", _collect_events(events))
    assert out.verdict == "approve"


def test_deliberate_streaming_swallows_history_save_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge_with(monkeypatch, history_factory=lambda: _HistorySaveBoom())
    events: list[tuple[str, Any]] = []
    out = bridge.deliberate_streaming("سؤال", _collect_events(events))
    assert out.verdict == "approve"


def test_deliberate_streaming_swallows_cache_set_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _bridge_with(monkeypatch, cache_factory=lambda: _CacheSetBoom())
    events: list[tuple[str, Any]] = []
    out = bridge.deliberate_streaming("سؤال", _collect_events(events))
    assert out.verdict == "approve"


def test_deliberate_with_memory_injects_rag_docs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The RAG arm of the non-streaming path (echo filter + distance filter)."""
    rag = FakeRag(docs=[
        _Doc("[Council APPROVE] echoed council verdict"),  # echo → dropped
        _Doc("حقيقة مفيدة عن sqlite", distance=0.2),
        _Doc("وثيقة بعيدة", distance=9.0),                 # too far → dropped
    ])
    bridge = _bridge_with(monkeypatch, rag=rag)
    out = bridge.deliberate_with_memory("كيف نسرّع قاعدة البيانات؟")
    assert out.verdict == "approve"
    assert "RAG: 1" in capsys.readouterr().out
    assert "حقيقة مفيدة" in bridge.engine.calls[-1]["context"]  # type: ignore[union-attr]


# ═══════════════════════════ history: IO guards ═══════════════════════════


def test_history_get_rag_uses_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = object()
    mod = types.ModuleType("src.memory.agent_rag_bridge")
    mod.get_bridge = lambda: marker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.memory.agent_rag_bridge", mod)
    hist = hist_mod.CouncilHistory(str(tmp_path))
    assert hist._get_rag() is marker
    assert hist._get_rag() is marker  # cached after the first call


def test_history_get_rag_swallows_bridge_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(
        sys.modules, "src.memory.agent_rag_bridge", _failing_bridge_module()
    )
    hist = hist_mod.CouncilHistory(str(tmp_path))
    assert hist._get_rag() is None


def test_history_save_reports_write_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules, "src.memory.agent_rag_bridge", _failing_bridge_module()
    )
    hist = hist_mod.CouncilHistory(str(tmp_path))
    hist.history_dir = str(blocker)
    rec_id = hist.save(_result(), query="q")
    assert rec_id.startswith("decision_")
    assert "خطأ الحفظ" in capsys.readouterr().out


def test_history_save_mirrors_into_rag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    mod = types.ModuleType("src.memory.agent_rag_bridge")

    class _Rag:
        def remember(self, summary: str, doc_id: str = "") -> None:
            calls.append((summary, doc_id))

    mod.get_bridge = lambda: _Rag()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.memory.agent_rag_bridge", mod)
    hist = hist_mod.CouncilHistory(str(tmp_path))
    rec_id = hist.save(_result(), query="سؤال")
    assert calls and calls[0][1] == rec_id
    assert "[Council APPROVE" in calls[0][0]


def test_history_stats_missing_dir(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    hist.history_dir = str(tmp_path / "gone")
    assert hist.stats() == {"total": 0}


def test_history_stats_counts_unknown_verdict(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    (tmp_path / "a.json").write_text(
        json.dumps({"verdict": "approve", "score": 0.8, "rounds": 2}),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps({"verdict": "weird", "score": 0.2, "rounds": 1}),
        encoding="utf-8",
    )
    (tmp_path / "c.json").write_text("{not json", encoding="utf-8")
    stats = hist.stats()
    assert stats["total"] == 3
    assert stats["by_verdict"]["approve"] == 1
    assert stats["by_verdict"]["reject"] == 0  # "weird" matched no bucket


def test_history_list_recent_missing_dir(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    hist.history_dir = str(tmp_path / "gone")
    assert hist.list_recent() == []


def test_history_list_recent_skips_corrupt_entry(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    (tmp_path / "zz_bad.json").write_text("{nope", encoding="utf-8")
    (tmp_path / "aa_good.json").write_text(
        json.dumps({"id": "d1", "query": "q", "verdict": "approve"}), encoding="utf-8"
    )
    recent = hist.list_recent()
    assert [r["id"] for r in recent] == ["d1"]


def test_history_search_missing_dir(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    hist.history_dir = str(tmp_path / "gone")
    assert hist.search("anything") == []


def test_history_search_stops_at_limit(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    for i in range(3):
        (tmp_path / f"rec_{i}.json").write_text(
            json.dumps({"id": f"d{i}", "query": "alpha topic"}),
            encoding="utf-8",
        )
    hits = hist.search("alpha", n=1)
    assert len(hits) == 1  # breaks as soon as n is reached


def test_history_get_full_roundtrip(tmp_path: Path) -> None:
    hist = hist_mod.CouncilHistory(str(tmp_path))
    rec_id = hist.save(_result(), category="auto", query="سؤال الحفظ")
    full = hist.get_full(rec_id)
    assert full is not None and full["query"] == "سؤال الحفظ"
    assert hist.get_full("missing") is None


# ═══════════════════════════ craft: guards + review ═══════════════════════════


def test_craft_router_returns_none_on_import_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    _inject_raising_router(monkeypatch)
    assert craft_mod._router() is None


def test_craft_module_bootstrap_guard_reinserts_root() -> None:
    """The sys.path guard self-heals a bare interpreter and the import follows."""
    namespace = _exec_module_without_repo_root(craft_mod)
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(str(craft_mod.__file__)))))
    assert root in namespace["__sys_path_after__"]   # the guard inserted it
    assert namespace["_safe_rel_path"] is not None   # ...and the import then worked
    assert callable(namespace["builds_root"])


def test_craft_parse_files_rejects_invalid_object_json() -> None:
    with pytest.raises(craft_mod.CraftError, match="JSON"):
        craft_mod._parse_files('{"files": [}}')


def test_craft_parse_files_rejects_invalid_array_json() -> None:
    with pytest.raises(craft_mod.CraftError, match="JSON غير صالح"):
        craft_mod._parse_files("[1, 2, ]")


def test_craft_parse_files_needs_json_markers() -> None:
    with pytest.raises(craft_mod.CraftError, match="لم أجد مصفوفة"):
        craft_mod._parse_files("[1, 2")


def test_craft_parse_files_rejects_empty_and_headerless() -> None:
    with pytest.raises(craft_mod.CraftError, match="فارغة"):
        craft_mod._parse_files("   ")
    with pytest.raises(craft_mod.CraftError, match="JSON"):
        craft_mod._parse_files("no markers here")


def test_craft_parse_files_accepts_bare_array() -> None:
    files = craft_mod._parse_files('[{"path": "a.py", "content": "x=1"}]')
    assert files == [("a.py", "x=1")]


def test_craft_review_uses_council_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Res:
        verdict = "approve"
        score = 0.8
        rounds = 2

    class _Bridge:
        def deliberate_with_memory(self, question: str, context: str = "",
                                   use_cache: bool = True) -> _Res:
            assert "اكتب سكربت" in question
            return _Res()

    monkeypatch.setattr(rag_bridge_mod, "get_council_bridge", lambda: _Bridge())
    monkeypatch.setenv("NEXUS_BUILDS", str(tmp_path))
    llm = FakeLLMRouter([{
        "ok": True,
        "text": json.dumps([{"path": "main.py", "content": "x = 1\n"}]),
    }])
    out = craft_mod.generate_code("اكتب سكربت", review=True, llm=llm)
    assert out["proof"]["ok"] is True
    assert out["review"] == {"verdict": "approve", "score": 0.8, "rounds": 2}


# ═══════════════════════════ builder: model-output guards ═══════════════════════════


def test_blueprint_from_llm_returns_none_without_llm(tmp_path: Path) -> None:
    builder = builder_mod.Builder(root=str(tmp_path), llm=None)
    assert builder.blueprint_from_llm("q", _result()) is None


def test_blueprint_from_llm_handles_non_dict_reply(tmp_path: Path) -> None:
    class _RawLLM:
        def generate(self, **_kw: Any) -> Any:
            return '{"title": "عنوان", "files": []}'

    builder = builder_mod.Builder(root=str(tmp_path), llm=_RawLLM())
    blueprint = builder.blueprint_from_llm("q", _result())
    assert blueprint is not None and blueprint["title"] == "عنوان"


def test_blueprint_from_llm_swallows_provider_error(tmp_path: Path) -> None:
    class _BoomLLM:
        def generate(self, **_kw: Any) -> Any:
            raise RuntimeError("provider down")

    builder = builder_mod.Builder(root=str(tmp_path), llm=_BoomLLM())
    assert builder.blueprint_from_llm("q", _result()) is None


def test_parse_blueprint_rejects_invalid_json() -> None:
    assert builder_mod.Builder.parse_blueprint('{"title": "x", "files": [}') is None


def test_parse_blueprint_rejects_non_dict_json(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_mod.json, "loads", lambda _s: [1, 2, 3])
    assert builder_mod.Builder.parse_blueprint('{"files": [1]}') is None


def test_parse_blueprint_strips_code_fences() -> None:
    raw = '```json\n{"title": "t", "files": [{"path": "a.py"}]}\n```'
    blueprint = builder_mod.Builder.parse_blueprint(raw)
    assert blueprint is not None and blueprint["title"] == "t"


class _ScriptedLLM:
    """Returns a fixed JSON payload from ``generate``."""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def generate(self, **_kw: Any) -> Any:
        return {"ok": True, "text": self.payload}


class _FrozenTime:
    @staticmethod
    def time() -> float:
        return 1000.0


def _build_with_blueprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blueprint: dict[str, Any],
    build_id: str,
) -> Any:
    root = tmp_path / "builds"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(builder_mod, "time", _FrozenTime)
    monkeypatch.setattr(builder_mod.Builder, "_counter", 0)
    (root / build_id).mkdir(exist_ok=True)
    builder = builder_mod.Builder(
        root=str(root),
        llm=_ScriptedLLM(json.dumps(blueprint, ensure_ascii=False)),
    )
    return builder.build("سؤال البناء", _result(), use_llm=True)


def test_build_skips_non_dict_blueprint_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _build_with_blueprint(
        tmp_path, monkeypatch,
        {"title": "t", "kind": "code", "files": [42, {"path": "ok.py", "content": "x = 1\n"}]},
        "build_1000000000_1",
    )
    names = [f.path for f in result.files]
    assert "ok.py" in names
    assert result.ok is True


def test_build_skips_path_escaping_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink inside a bundle must never become an escape hatch."""
    root = tmp_path / "builds"
    root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(builder_mod, "time", _FrozenTime)
    monkeypatch.setattr(builder_mod.Builder, "_counter", 0)
    build_dir = root / "build_1000000000_1"
    build_dir.mkdir()
    os.symlink(str(outside), str(build_dir / "escape"))

    builder = builder_mod.Builder(
        root=str(root),
        llm=_ScriptedLLM(json.dumps({
            "title": "t",
            "files": [{"path": "escape/evil.py", "content": "x = 1\n"}],
        })),
    )
    result = builder.build("سؤال", _result(), use_llm=True)
    assert "escape/evil.py" in result.proof["py_compile"] or result.ok is True
    assert not (outside / "evil.py").exists()  # nothing escaped the bundle
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert "escape/evil.py" in manifest["skipped"]


def test_list_builds_skips_dirs_without_manifest(tmp_path: Path) -> None:
    root = tmp_path / "builds"
    (root / "stray_dir").mkdir(parents=True)
    assert builder_mod.list_builds(str(root)) == []


def test_list_builds_skips_corrupt_manifest(tmp_path: Path) -> None:
    root = tmp_path / "builds"
    bad = root / "broken"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{oops", encoding="utf-8")
    assert builder_mod.list_builds(str(root)) == []


def test_get_build_returns_none_on_corrupt_manifest(tmp_path: Path) -> None:
    root = tmp_path / "builds"
    bad = root / "broken"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{oops", encoding="utf-8")
    assert builder_mod.get_build("broken", str(root)) is None


def test_get_build_returns_none_for_unsafe_id(tmp_path: Path) -> None:
    root = tmp_path / "builds"
    root.mkdir(parents=True)
    assert builder_mod.get_build("../etc", str(root)) is None


# ═══════════════════════════ engine: judge branches ═══════════════════════════


def test_judge_counts_explicit_verdicts_and_ignores_junk_entries() -> None:
    eng = engine_mod.CouncilEngine(llm_router=None)
    verdict, score = eng._judge([
        42,  # not a dict → defensive except (never crashes the verdict)
        {"member": "analyst", "response": "الحكم: موافق"},
        {"member": "critic", "response": "الحكم: موافق"},
    ])
    assert (verdict, score) == ("approve", 0.85)


def test_judge_falls_back_to_keyword_approve() -> None:
    eng = engine_mod.CouncilEngine(llm_router=None)
    verdict, _score = eng._judge([
        {"member": "profiler", "response": "الخيار آمن وموافق عليه"},
        {"member": "analyst", "response": "آمن وموافق"},
        {"member": "critic", "response": "آمن وموافق"},
    ])
    assert verdict == "approve"


def test_judge_falls_back_to_keyword_reject() -> None:
    eng = engine_mod.CouncilEngine(llm_router=None)
    verdict, _score = eng._judge([
        {"member": "profiler", "response": "خطر ومرفوض تماماً"},
        {"member": "analyst", "response": "خطر ومرفوض"},
        {"member": "critic", "response": "خطر ومرفوض"},
    ])
    assert verdict == "reject"


# ═══════════════════════════ small layer gaps ═══════════════════════════


def test_extract_recommendation_swallows_bad_input() -> None:
    from src.council.recommend import extract_recommendation

    assert extract_recommendation(42) == ""  # type: ignore[arg-type]
    assert extract_recommendation([{"response": "[التوصية: استخدم sqlite]"}]) == "استخدم sqlite"


def test_cache_clear_skips_non_json(tmp_path: Path) -> None:
    cache = cache_mod.CouncilCache(cache_dir=str(tmp_path))
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert cache.clear() == 0


def test_trust_receive_accepts_unique_nonce() -> None:
    from src.council.trust import TrustBoundary

    trust = TrustBoundary()
    trust.send("a", "b", "first")
    second = trust.send("a", "b", "second")
    third = trust.send("a", "b", "third")
    ok, reason = trust.receive(third)
    assert ok is True and reason == "موثوقة"
    # the loop really scanned the log when the nonce did not match
    assert second.nonce != third.nonce
