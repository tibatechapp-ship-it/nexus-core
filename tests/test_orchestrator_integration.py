"""Integration: Orchestrator plan + decompose + execute."""
import pytest

from src.orchestrator.orchestrator import (
    Orchestrator, decompose_enabled)
from src.orchestrator.risk import RiskLevel


def test_plan_low_risk_docs():
    o = Orchestrator()
    p = o.plan("add comment to foo")
    assert p.risk == RiskLevel.LOW
    assert p.agent == "documentation"


def test_plan_high_risk_genome():
    o = Orchestrator()
    p = o.plan("delete genome.json")
    assert p.risk == RiskLevel.HIGH


def test_execute_low_skips_jury():
    o = Orchestrator(jury_members=["a", "b"])
    r = o.execute("add comment", runner=lambda a, r: {"output": "ok", "ok": True})
    assert r["jury"] is None
    assert r["ok"] is True


def test_execute_high_invokes_jury():
    o = Orchestrator(jury_members=["a", "b"], llm=None)
    r = o.execute("delete genome entries",
                  runner=lambda a, r: {"output": "deleted", "ok": True})
    assert r["jury"] is not None
    assert r["jury"]["approved"] is False
    assert r["ok"] is False


# ── v1.24.0 decomposition ───────────────────────────────────────────────────
@pytest.fixture()
def _flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_DECOMPOSE", "0")


def test_decompose_flag_defaults_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_DECOMPOSE", raising=False)
    assert decompose_enabled() is True


def test_decompose_flag_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_DECOMPOSE", "0")
    assert decompose_enabled() is False


def test_execute_runs_each_subtask_in_order(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_DECOMPOSE", raising=False)
    seen = []

    def runner(agent, request):
        seen.append(agent)
        return {"output": f"[{agent}] {request}", "ok": True}

    r = Orchestrator().execute("write a sum function and test it", runner=runner)
    assert seen == ["coder", "tester"]
    assert r["decomposed"] is True
    assert [s["agent"] for s in r["subtasks"]] == ["coder", "tester"]
    assert "### write — coder" in r["output"]
    assert "### test — tester" in r["output"]
    assert r["ok"] is True


def test_execute_one_failing_subtask_marks_overall_not_ok(
        monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_DECOMPOSE", raising=False)

    def runner(agent, request):
        return {"output": "boom", "ok": agent != "tester"}

    r = Orchestrator().execute("write a sum function and test it", runner=runner)
    assert r["ok"] is False
    assert [x["ok"] for x in r["results"]] == [True, False]


def test_execute_runner_exception_is_captured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_DECOMPOSE", raising=False)

    def runner(agent, request):
        if agent == "tester":
            raise RuntimeError("provider down")
        return {"output": "ok", "ok": True}

    r = Orchestrator().execute("write a sum function and test it", runner=runner)
    assert r["ok"] is False
    assert "provider down" in (r["results"][1].get("error") or "")


def test_execute_merges_then_juries_once(
        monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NEXUS_DECOMPOSE", raising=False)
    calls = []

    def runner(agent, request):
        calls.append(agent)
        return {"output": "done", "ok": True}

    # one clause is HIGH ("delete"), the other MED → one jury over the block.
    r = Orchestrator(jury_members=["a", "b"], llm=None).execute(
        "delete the genome store and write a migration", runner=runner)
    assert r["decomposed"] is True
    assert r["jury"] is not None          # jury ran ONCE on the merged block
    assert r["jury"]["approved"] is False
    assert r["ok"] is False
    assert calls == [s["agent"] for s in r["subtasks"]]


def test_flag_off_is_the_single_agent_path(
        monkeypatch: pytest.MonkeyPatch, _flag_off: None):
    seen = []

    def runner(agent, request):
        seen.append((agent, request))
        return {"output": "ok", "ok": True}

    r = Orchestrator().execute("write a sum function and test it", runner=runner)
    assert len(seen) == 1                 # NOT decomposed
    assert "decomposed" not in r
    assert seen[0][1] == "write a sum function and test it"


def test_no_runner_returns_empty_shell():
    r = Orchestrator().execute("write a sum function")
    assert r["output"] is None and r["ok"] is None and r["jury"] is None


def test_single_path_runner_exception_captured():
    def boom(agent, request):
        raise RuntimeError("single provider down")

    r = Orchestrator().execute("write a sum function", runner=boom)
    assert r["ok"] is False
    assert "single provider down" in (r["error"] or "")
    assert "decomposed" not in r


def _approving_judge(*_a, **_k):
    class _V:
        def __init__(self) -> None:
            self.approved = True
            self.confidence = 0.9
            self.blocking: list = []
            self.abstentions: list = []

    return _V()


def test_high_risk_jury_approval_keeps_ok(monkeypatch: pytest.MonkeyPatch):
    import src.novamind.council.jury as jury_mod
    monkeypatch.setattr(jury_mod, "judge", _approving_judge)

    r = Orchestrator(jury_members=["a", "b"], llm=None).execute(
        "delete genome entries",
        runner=lambda a, req: {"output": "done", "ok": True})
    assert r["jury"] is not None
    assert r["jury"]["approved"] is True
    assert r["ok"] is True
