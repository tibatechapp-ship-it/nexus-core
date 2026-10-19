"""Jury gate tests."""
from src.novamind.council.jury import judge
from src.orchestrator.risk import RiskLevel


class FakeLLM:
    def __init__(self, approved, confidence=0.9):
        self.approved = approved
        self.confidence = confidence
    def generate(self, prompt, **kw):
        return '{"approved": %s, "confidence": %s, "issues": []}' % (
            "true" if self.approved else "false", self.confidence)


def test_low_returns_none():
    assert judge("x", risk=RiskLevel.LOW, members=["a"], llm=FakeLLM(True)) is None


def test_med_returns_none():
    assert judge("x", risk=RiskLevel.MED, members=["a"], llm=FakeLLM(True)) is None


def test_high_majority_approve():
    v = judge("x", risk=RiskLevel.HIGH, members=["a", "b", "c"], llm=FakeLLM(True))
    assert v.approved is True
    assert v.members_approved == 3


def test_high_all_abstain_fail_closed():
    v = judge("x", risk=RiskLevel.HIGH, members=["a", "b"], llm=None)
    assert v.approved is False
    assert "all_members_abstained" in v.blocking_issues


def test_high_majority_reject():
    v = judge("x", risk=RiskLevel.HIGH, members=["a", "b", "c"], llm=FakeLLM(False, 0.8))
    assert v.approved is False
