"""Integration: Orchestrator plan + execute."""
from src.orchestrator.orchestrator import Orchestrator
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
