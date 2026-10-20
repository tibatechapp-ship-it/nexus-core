"""The council is a black box: internal deliberation must not leak (v1.26.1).

Covers the API-level hiding (``NEXUS_UI_VERBOSE``) plus the developers-only
trace, so no interface — old TUI, old web console, new UI — can render the
individual jurors by default.
"""
from __future__ import annotations

import json

import pytest

from src.orchestrator.orchestrator import Orchestrator, _public_jury
from src.novamind.council.jury import JuryVerdict, judge, trace_path
from src.orchestrator.risk import RiskLevel


class _FakeLLM:
    """Deterministic jury member: always approves with a fixed confidence."""

    def generate(self, prompt: str, **kwargs: object) -> str:
        return '{"approved": true, "confidence": 0.9, "issues": []}'


def _verdict() -> JuryVerdict:
    return JuryVerdict(
        approved=True,
        confidence=0.9,
        blocking_issues=[],
        members_consulted=3,
        members_approved=3,
        member_verdicts={"profiler": {"approved": True}, "analyst": {"approved": True}},
    )


# ── 1. hidden by default ────────────────────────────────────────────────────

def test_council_hidden_by_default(monkeypatch):
    """With no NEXUS_UI_VERBOSE, only the decision leaves the API."""
    monkeypatch.delenv("NEXUS_UI_VERBOSE", raising=False)
    public = _public_jury(_verdict())

    assert public == {"approved": True, "confidence": 0.9}
    # the jurors' identities / details never reach a caller
    for leaked in ("member_verdicts", "members_consulted",
                   "members_approved", "blocking_issues"):
        assert leaked not in public


# ── 2. verbose when requested ───────────────────────────────────────────────

def test_council_verbose_when_requested(monkeypatch):
    """NEXUS_UI_VERBOSE=1 exposes the full verdict for developers."""
    monkeypatch.setenv("NEXUS_UI_VERBOSE", "1")
    public = _public_jury(_verdict())

    assert set(public) == {"approved", "confidence", "blocking_issues",
                           "members_consulted", "members_approved",
                           "member_verdicts"}
    assert set(public["member_verdicts"]) == {"profiler", "analyst"}


# ── 3. the deliberation is never lost — it goes to the developer trace ───────

def test_trace_logged(monkeypatch, tmp_path):
    """judge() appends the full verdict to data/council_trace.jsonl."""
    trace = tmp_path / "council_trace.jsonl"
    monkeypatch.setenv("NEXUS_COUNCIL_TRACE", str(trace))

    verdict = judge("delete genome entries", risk=RiskLevel.HIGH,
                    members=["profiler", "analyst"], llm=_FakeLLM())

    assert verdict is not None and verdict.approved is True
    assert trace_path() == trace
    lines = trace.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["target"] == "delete genome entries"
    assert record["verdict"]["member_verdicts"].keys() == {"profiler", "analyst"}
    assert record["ts"]


# ── integration: the orchestrator response obeys the same switch ────────────

def test_orchestrator_result_uses_the_switch(monkeypatch):
    """execute()'s jury field follows NEXUS_UI_VERBOSE end to end."""
    monkeypatch.setenv("NEXUS_COUNCIL_TRACE", "/dev/null")

    monkeypatch.setenv("NEXUS_UI_VERBOSE", "0")
    orch = Orchestrator(jury_members=["profiler", "analyst"], llm=_FakeLLM())
    orch.llm = _FakeLLM()
    result: dict = {"output": "delete genome entries"}
    orch._apply_jury(result, RiskLevel.HIGH)
    assert set(result["jury"]) == {"approved", "confidence"}

    monkeypatch.setenv("NEXUS_UI_VERBOSE", "1")
    result = {"output": "delete genome entries"}
    orch._apply_jury(result, RiskLevel.HIGH)
    assert "member_verdicts" in result["jury"]


@pytest.mark.parametrize("flavour", ["", "off", "no", "false", "0"])
def test_anything_but_truthy_keeps_it_hidden(monkeypatch, flavour):
    """Rollback safety: only an explicit truthy value enables verbose."""
    if flavour:
        monkeypatch.setenv("NEXUS_UI_VERBOSE", flavour)
    else:
        monkeypatch.delenv("NEXUS_UI_VERBOSE", raising=False)
    assert _public_jury(_verdict()) == {"approved": True, "confidence": 0.9}


# ── BUG-C: a decomposed HIGH task MUST reach the jury (v1.31.4) ──────────────

def test_decomposed_high_risk_still_reaches_the_jury(monkeypatch):
    """Regression for the max() mispick — top_risk must be the HIGHEST subtask.

    Before the fix, ``max([HIGH, MED])`` returned MED, so a decomposed HIGH
    request silently skipped the jury gate. The runner is a no-op stub and the
    only assertion is that the jury FIRED.
    """
    from src.orchestrator.decomposer import SubTask

    monkeypatch.setenv("NEXUS_COUNCIL_TRACE", "/dev/null")
    monkeypatch.setenv("NEXUS_UI_VERBOSE", "0")

    orch = Orchestrator(jury_members=["profiler", "analyst"], llm=_FakeLLM())
    orch.llm = _FakeLLM()
    subtasks = [
        SubTask(agent="coder", request="list files", risk=RiskLevel.LOW),
        SubTask(agent="analyst", request="add comment", risk=RiskLevel.MED),
        SubTask(agent="recovery", request="delete genome", risk=RiskLevel.HIGH),
    ]
    result = orch._execute_many("do three things", subtasks,
                                lambda agent, req: {"output": f"{agent} ok", "ok": True})

    assert result.get("jury") is not None, "HIGH subtask must convene the jury"
    assert result["jury"]["approved"] is True

