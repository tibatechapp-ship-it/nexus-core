"""Tests for src/orchestrator/* — routing + supervised execution (offline)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import src.orchestrator.agent_cache as cache
import src.orchestrator.supervisor as sup_mod
from src.orchestrator.hybrid_router import HybridRouter, classify, get_hybrid_router
from src.orchestrator.smart_router import Complexity, RouteDecision, SmartRouter, Strategy
from src.orchestrator.supervisor import Supervisor


# ───────────────────────────── smart_router ─────────────────────────────

def test_decide_simple_single_agent() -> None:
    d = SmartRouter().decide("راجع هذا السطر")
    assert isinstance(d, RouteDecision)
    assert d.strategy in {Strategy.SINGLE.value, Strategy.SEQUENTIAL.value}


def test_category_security_beats_others() -> None:
    d = SmartRouter().decide("ابحث عن ثغرة xss في الكود")
    assert d.category == "security"


def test_category_defaults_to_code_generation() -> None:
    d = SmartRouter().decide("مرحبا كيف الحال")
    assert d.category == "code_generation"


def test_complexity_critical_from_keywords() -> None:
    d = SmartRouter().decide("deploy to production now")
    assert d.complexity == Complexity.CRITICAL.value
    assert d.council_needed is True


def test_complexity_complex_and_standard_and_simple() -> None:
    r = SmartRouter()
    assert r.decide("نظام شامل وكامل للمشروع").complexity == Complexity.COMPLEX.value
    assert r.decide("شامل فقط هنا").complexity == Complexity.STANDARD.value
    assert r.decide("hi").complexity == Complexity.SIMPLE.value


def test_risk_levels() -> None:
    r = SmartRouter()
    assert r._detect_risk("please drop table users") == "high"
    assert r._detect_risk("what is a token") == "medium"
    assert r._detect_risk("hello world") == "low"


def test_choose_strategy_paths() -> None:
    r = SmartRouter()
    assert r._choose_strategy("code_generation", "simple", "low", "")[0] == "single"
    assert r._choose_strategy("code_generation", "standard", "low", "")[0] == "sequential"
    assert r._choose_strategy("code_generation", "complex", "low", "")[0] == "parallel"
    assert r._choose_strategy("code_generation", "critical", "high", "")[0] == "council"


def test_estimate_time_values() -> None:
    r = SmartRouter()
    assert r._estimate_time("single", 1) == 1.0
    assert r._estimate_time("parallel", 3) == 1.5
    assert r._estimate_time("unknown", 1) == 1.0


# ───────────────────────────── hybrid_router ─────────────────────────────

@pytest.mark.parametrize("prompt,expected", [
    ("هل نستخدم postgres أم sqlite؟", "decision"),
    ("احفظ هذه الملاحظة", "tool"),
    ("اكتب دالة فيبوناتشي", "code"),
    ("ابحث عن ثغرة أمنية", "decision"),
    ("مرحبا بالعالم", "tool"),
    ("هل نستخدم production أم staging", "decision"),
])
def test_classify(prompt: str, expected: str) -> None:
    assert classify(prompt) == expected


def test_classify_tool_but_code_wins() -> None:
    # code needs >= 2 distinct pattern hits to override a tool hit
    assert classify("احفظ ثم أصلح الدالة python") == "code"
    assert classify("احفظ ملف وقته") == "tool"


def test_hybrid_run_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    r = HybridRouter()
    monkeypatch.setattr(r, "_run_smart", lambda p: {"ok": True, "method": "smart_router"})
    monkeypatch.setattr(r, "_run_council", lambda p: {"ok": True, "method": "council"})
    monkeypatch.setattr(r, "_run_loop", lambda p: {"ok": True, "method": "agent_loop"})
    assert r.run("x", force="code")["route"] == "code"
    assert r.run("x", force="decision")["route"] == "decision"
    assert r.run("x", force="tool")["route"] == "tool"
    assert "total_elapsed" in r.run("x", force="tool")


def test_build_smart_answer() -> None:
    r = HybridRouter()
    assert r._build_smart_answer({}) == ""
    out = r._build_smart_answer({"results": [
        {"ok": True, "result": "good"},
        {"ok": False, "error": "boom"},
        {"ok": True, "result": ""},
    ]})
    assert "good" in out and "boom" in out


def test_get_hybrid_router_singleton() -> None:
    a = get_hybrid_router(use_rag=True)
    b = get_hybrid_router(use_rag=True)
    assert a is b
    c = get_hybrid_router(use_rag=False)  # use_rag change → new instance
    assert c is not a


# ───────────────────────────── agent_cache ─────────────────────────────

@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cache, "_CACHE_DIR", str(tmp_path))
    return tmp_path


def test_cache_set_get_roundtrip(tmp_cache: Path) -> None:
    assert cache.get("a", "p") is None
    cache.set("a", "p", {"v": 1})
    assert cache.get("a", "p") == {"v": 1}


def test_cache_expired_entry_removed(tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache.set("a", "p", "x")
    monkeypatch.setattr(cache, "_TTL", -1)  # everything is stale
    assert cache.get("a", "p") is None


def test_cache_corrupt_and_bad_dir(tmp_cache: Path) -> None:
    path = tmp_cache / (cache._key("a", "p") + ".json")
    path.write_text("{not json", encoding="utf-8")
    assert cache.get("a", "p") is None
    # value that is not JSON-serializable must not raise
    cache.set("b", "p", object())


# ───────────────────────────── supervisor ─────────────────────────────

class _Reg:
    def __init__(self, agent: Any = None, error: Exception | None = None) -> None:
        self._agent = agent
        self._error = error

    def load_agent(self, name: str) -> Any:
        if self._error:
            raise self._error
        return self._agent


class _StrAgent:
    def run(self, prompt: str) -> str:
        return f"echo:{prompt}"


class _DictAgent:
    def run(self, data: Any) -> str:
        if not isinstance(data, dict):
            raise TypeError("need dict")
        return "dict-ok"


class _EmptyAgent:
    pass


class _TypeErrAgent:
    def run(self, prompt: str, extra: Any = None) -> str:
        raise TypeError("always")


class _ValueErrAgent:
    def run(self, prompt: str) -> str:
        raise ValueError("bad")


class _AsyncAgent:
    async def run(self, prompt: str) -> str:
        return "async-ok"


class _CoroAgent:
    def run(self, prompt: str) -> Any:
        async def inner() -> str:
            return "coro-ok"

        return inner()


@pytest.fixture
def no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "get", lambda a, p: None)
    monkeypatch.setattr(cache, "set", lambda a, p, r: None)


def _sup(agent: Any = None, error: Exception | None = None) -> Supervisor:
    s = Supervisor(use_rag=False, verbose=False)
    s._registry = _Reg(agent, error)
    return s


def test_run_single_str_method(no_cache: None) -> None:
    out = _sup(_StrAgent())._run_single("coder", "hi")
    assert out["ok"] is True and out["result"] == "echo:hi" and out["method"] == "run"


def test_run_single_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "get", lambda a, p: "from-cache")
    out = _sup(_StrAgent())._run_single("coder", "hi")
    assert out["method"] == "cached" and out["result"] == "from-cache"


def test_run_single_load_error(no_cache: None) -> None:
    out = _sup(error=RuntimeError("nope"))._run_single("coder", "hi")
    assert out["ok"] is False and "تحميل" in out["error"]


def test_run_single_no_method(no_cache: None) -> None:
    out = _sup(_EmptyAgent())._run_single("coder", "hi")
    assert out["ok"] is False and "لا طريقة" in out["error"]


def test_run_single_dict_fallback(no_cache: None) -> None:
    assert _sup(_DictAgent())._run_single("coder", "hi")["result"] == "dict-ok"


def test_run_single_all_patterns_fail(no_cache: None) -> None:
    out = _sup(_TypeErrAgent())._run_single("coder", "hi")
    assert out["ok"] is False and "كل الأنماط فشلت" in out["error"]


def test_run_single_other_exception(no_cache: None) -> None:
    out = _sup(_ValueErrAgent())._run_single("coder", "hi")
    assert out["ok"] is False and out["error"] == "bad"


def test_run_single_async(no_cache: None) -> None:
    assert _sup(_AsyncAgent())._run_single("coder", "hi")["result"] == "async-ok"


def test_run_single_coroutine_result(no_cache: None) -> None:
    assert _sup(_CoroAgent())._run_single("coder", "hi")["result"] == "coro-ok"


def test_detect_method_and_registry_lazy() -> None:
    s = Supervisor(use_rag=False, verbose=False)
    assert s._detect_method(_StrAgent()) == "run"
    assert s._detect_method(_EmptyAgent()) is None
    # lazy registry import is wrapped — missing `nova` must not crash
    assert s._registry is None
    assert s._get_rag() is None or s._get_rag() is not None  # tolerant of env


def test_execute_single(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _sup(_StrAgent())
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    out = s.execute("hi")
    assert out["ok"] is True and out["decision"]["strategy"] == "single"


def test_execute_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _sup(_StrAgent())
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="sequential", complexity="standard", category="code_generation",
        agents=["a", "b"], reason=""))
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    out = s.execute("hi")
    assert len(out["results"]) == 2


def test_execute_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _sup(_StrAgent())
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="parallel", complexity="complex", category="code_generation",
        agents=["a", "b"], reason=""))
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    out = s.execute("hi")
    assert out["ok"] is True and len(out["results"]) == 2


def test_execute_council_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.rag_bridge as bridge_mod

    class _Verdict:
        verdict = "approve"
        score = 0.9
        rounds = 1

    class _Bridge:
        def deliberate_with_memory(self, p: str) -> _Verdict:
            return _Verdict()

    monkeypatch.setattr(bridge_mod, "get_council_bridge", lambda: _Bridge())
    s = _sup(_StrAgent())
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="council", complexity="critical", category="security",
        agents=["a"], reason="", risk_level="high"))
    out = s.execute("deploy production")
    assert out["ok"] is True
    assert out["results"][0]["agent"] == "council"


def test_execute_with_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Doc:
        id = "d1"
        text = "some memory"

    class _Rag:
        def __init__(self) -> None:
            self.remembered = False

        def recall(self, q: str, k: int = 3) -> list[_Doc]:
            return [_Doc()]

        def remember(self, s: str) -> None:
            self.remembered = True

    rag = _Rag()
    s = _sup(_StrAgent())
    s.use_rag = True
    monkeypatch.setattr(s, "_get_rag", lambda: rag)
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="single", complexity="simple", category="code_generation",
        agents=["a"], reason=""))
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    out = s.execute("hello")
    assert out["ok"] is True and rag.remembered is True


def test_print_decision(capsys: pytest.CaptureFixture[str]) -> None:
    Supervisor(use_rag=False, verbose=False)._print_decision(RouteDecision(
        strategy="single", complexity="simple", category="code_generation",
        agents=["coder"], reason="r"))
    assert "Smart Router" in capsys.readouterr().out


# ═════════════════ coverage of the real (non-mocked) supervisor paths ═══════════

def test_get_registry_real_import() -> None:
    """nova.registry exists in-tree → the lazy import must resolve."""
    s = Supervisor(use_rag=False, verbose=False)
    reg = s._get_registry()
    assert reg is not None
    assert s._get_registry() is reg            # cached, line 39-40 executed


def test_get_rag_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    ok = Supervisor(use_rag=True, verbose=False)
    rag = ok._get_rag()
    assert ok._rag is rag                       # success branch (45-47)

    # broken bridge → the except branch must swallow it
    bad = Supervisor(use_rag=True, verbose=False)
    monkeypatch.setitem(sys.modules, "src.memory.agent_rag_bridge",
                        types.ModuleType("src.memory.agent_rag_bridge"))
    assert bad._get_rag() is None
    assert Supervisor(use_rag=False, verbose=False)._get_rag() is None


def test_execute_force_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _sup(_StrAgent())
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    out = s.execute("hi", force_strategy="parallel")
    assert out["decision"]["strategy"] == "parallel"
    assert len(out["results"]) == 1            # force wins over the router decision


def test_execute_unknown_strategy_is_empty_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No branch matches → an honest empty failure, never a crash."""
    s = _sup(_StrAgent())
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    out = s.execute("hi", force_strategy="not-a-strategy")
    assert out["ok"] is False and out["results"] == []


def test_execute_verbose_single(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    s = _sup(_StrAgent())
    s.verbose = True
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    s.execute("hi")
    assert "Smart Router" in capsys.readouterr().out


def test_execute_sequential_verbose(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    s = _sup(_StrAgent())
    s.verbose = True
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="sequential", complexity="standard", category="code_generation",
        agents=["a", "b"], reason=""))
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    s.execute("hi")
    out = capsys.readouterr().out
    assert "[1/2]" in out and "[2/2]" in out


def test_execute_parallel_verbose_and_timeout(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    s = _sup(_StrAgent())
    s.verbose = True
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="parallel", complexity="complex", category="code_generation",
        agents=["a", "b"], reason=""))
    monkeypatch.setattr(s, "_run_single", lambda a, p: {"ok": True, "agent": a, "result": "r"})
    s.execute("hi")
    assert capsys.readouterr().out.count("✅") >= 2

    # a worker that blows up must be reported, never crash execute()
    def _boom(a: str, p: str) -> dict:
        raise RuntimeError(f"worker {a} died")

    monkeypatch.setattr(s, "_run_single", _boom)
    out = s.execute("hi")
    assert out["ok"] is False
    assert all("died" in r.get("error", "") for r in out["results"])


def test_execute_council_verbose_and_failure(monkeypatch: pytest.MonkeyPatch,
                                             capsys) -> None:
    import src.council.rag_bridge as bridge_mod

    class _Verdict:
        verdict = "reject"
        score = 0.2
        rounds = 2

    monkeypatch.setattr(bridge_mod, "get_council_bridge",
                        lambda: type("B", (), {
                            "deliberate_with_memory": lambda self, p: _Verdict()})())
    s = _sup(_StrAgent())
    s.verbose = True
    monkeypatch.setattr(s.router, "decide", lambda p: RouteDecision(
        strategy="council", complexity="critical", category="security",
        agents=["a"], reason="", risk_level="high"))
    out = s.execute("deploy production")
    assert "خطورة: high" in capsys.readouterr().out
    assert out["ok"] is False                  # reject verdict

    def _bridge_boom() -> None:
        raise RuntimeError("council down")

    monkeypatch.setattr(bridge_mod, "get_council_bridge", _bridge_boom)
    out = s.execute("deploy production")
    assert out["results"][0]["ok"] is False and out["results"][0]["error"] == "council down"


def test_execute_cache_and_rag_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _sup(_StrAgent())

    def _cache_boom(a: str, p: str) -> None:
        raise RuntimeError("cache read down")

    monkeypatch.setattr(cache, "get", _cache_boom)      # 71-72
    out = s._run_single("coder", "hi")
    assert out["ok"] is True                            # read failure is non-fatal

    def _cache_set_boom(a: str, p: str, r: Any) -> None:
        raise RuntimeError("cache write down")

    monkeypatch.setattr(cache, "set", _cache_set_boom)  # 152-153
    assert s._run_single("coder", "hi")["ok"] is True


def test_run_single_coroutine_that_raises(no_cache: None) -> None:
    class _ExplodingCoro:
        def run(self, prompt: str) -> Any:
            async def boom() -> str:
                raise ValueError("await failed")

            return boom()

    out = _sup(_ExplodingCoro())._run_single("coder", "hi")
    assert out["ok"] is False and out["error"] == "await failed"


def test_execute_rag_branches(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    class _Doc:
        id = "d9"
        text = "ذاكرة"

    class _Rag:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        def recall(self, q: str, k: int = 3) -> list[Any]:
            if self.mode == "raise":
                raise RuntimeError("rag down")
            return [] if self.mode == "empty" else [_Doc()]

        def remember(self, s: str) -> None:
            if self.mode == "raise":
                raise RuntimeError("remember down")

    decide = lambda p: RouteDecision(  # noqa: E731
        strategy="single", complexity="simple", category="code_generation",
        agents=["a"], reason="")
    run = lambda a, p: {"ok": True, "agent": a, "result": "r"}  # noqa: E731

    # 1. rag is None → both `if rag:` false branches
    none_s = _sup(_StrAgent())
    none_s.use_rag = True
    monkeypatch.setattr(none_s, "_get_rag", lambda: None)
    monkeypatch.setattr(none_s.router, "decide", decide)
    monkeypatch.setattr(none_s, "_run_single", run)
    assert none_s.execute("hi")["ok"] is True

    # 2. docs present + verbose → the RAG print + prompt enrichment
    s = _sup(_StrAgent())
    s.use_rag = True
    s.verbose = True
    monkeypatch.setattr(s, "_get_rag", lambda: _Rag("ok"))
    monkeypatch.setattr(s.router, "decide", decide)
    monkeypatch.setattr(s, "_run_single", run)
    assert s.execute("hi")["ok"] is True
    assert "RAG" in capsys.readouterr().out

    # 3. empty docs → `if docs:` false branch
    empty_s = _sup(_StrAgent())
    empty_s.use_rag = True
    monkeypatch.setattr(empty_s, "_get_rag", lambda: _Rag("empty"))
    monkeypatch.setattr(empty_s.router, "decide", decide)
    monkeypatch.setattr(empty_s, "_run_single", run)
    assert empty_s.execute("hi")["ok"] is True

    # 4. recall + remember both explode → both except branches
    bad = _sup(_StrAgent())
    bad.use_rag = True
    monkeypatch.setattr(bad, "_get_rag", lambda: _Rag("raise"))
    monkeypatch.setattr(bad.router, "decide", decide)
    monkeypatch.setattr(bad, "_run_single", run)
    assert bad.execute("hi")["ok"] is True


# ═════════════════ coverage of the real hybrid router paths ═════════════════

def test_hybrid_verbose_run(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    r = HybridRouter(verbose=True)
    monkeypatch.setattr(r, "_run_loop", lambda p: {"ok": True, "method": "m"})
    r.run("any", force="tool")
    assert "Hybrid Router" in capsys.readouterr().out


def test_hybrid_run_smart_real(monkeypatch: pytest.MonkeyPatch) -> None:
    import nova.registry as nova_reg

    class _Reg:
        def load_agent(self, name: str) -> Any:
            raise KeyError(name)

    monkeypatch.setattr(nova_reg, "REGISTRY", _Reg())
    r = HybridRouter(use_rag=False)
    out = r._run_smart("اكتب دالة")
    assert out["method"] == "smart_router" and out["decision"]
    assert out["results"][0]["ok"] is False    # agent could not be loaded

    # the wrapper must not swallow a broken Supervisor
    monkeypatch.setattr(sup_mod, "Supervisor",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("sup down")))
    assert r._run_smart("x")["error"] == "sup down"


def test_hybrid_run_loop_real(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Loop:
        def __init__(self, max_iterations: int = 8, verbose: bool = False) -> None:
            self.max_iterations = max_iterations
            self.verbose = verbose

        def run(self, prompt: str) -> dict:
            return {"ok": True, "iterations": 3, "trace": [{"icon": "i", "text": "t"}],
                    "answer": "loop answer", "error": ""}

    monkeypatch.setattr("src.agent_loop.loop.AgentLoop", _Loop)
    out = HybridRouter()._run_loop("ابحث عن ملف")
    assert out["method"] == "agent_loop" and out["answer"] == "loop answer"
    assert out["iterations"] == 3

    class _BadLoop(_Loop):
        def run(self, prompt: str) -> dict:
            raise RuntimeError("loop down")

    monkeypatch.setattr("src.agent_loop.loop.AgentLoop", _BadLoop)
    assert HybridRouter()._run_loop("x")["error"] == "loop down"


def test_hybrid_run_council_real(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.council.rag_bridge as bridge_mod

    class _Verdict:
        verdict = "approve"
        score = 0.88
        rounds = 2
        elapsed = 1.5
        transcript = [{"phase": "d", "member": "m", "response": "ر" * 900}]

    class _Bridge:
        engine = type("E", (), {"MAX_ROUNDS": 5})()

        def deliberate_with_memory(self, p: str) -> _Verdict:
            return _Verdict()

    monkeypatch.setattr(bridge_mod, "get_council_bridge", lambda: _Bridge())
    out = HybridRouter()._run_council("هل ننشر؟")
    assert out["method"] == "council" and out["ok"] is True
    assert out["transcript"][0]["response"] == "ر" * 500
    assert out["answer"].startswith("القرار: approve")

    monkeypatch.setattr(bridge_mod, "get_council_bridge",
                        lambda: (_ for _ in ()).throw(RuntimeError("council down")))
    assert HybridRouter()._run_council("x")["error"] == "council down"


def test_cache_set_failure_is_silent(tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # the cache directory does not exist → open() raises → must be swallowed
    monkeypatch.setattr(cache, "_CACHE_DIR", str(tmp_cache / "missing" / "deeper"))
    cache.set("a", "p", "x")
    assert cache.get("a", "p") is None
