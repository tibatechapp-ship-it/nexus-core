"""Tests for ``src.orchestrator.decomposer`` — task decomposition (v1.24.0).

Pure module (no LLM, no I/O), so these are fully hermetic. The lexicon is
validated against the real agent registry so a typo in an agent id can never
silently ship.
"""
from __future__ import annotations

from typing import List

import pytest

from src.orchestrator.decomposer import (
    SubTask, decompose, merge_outputs, split_clauses, _LEXICON)
from src.orchestrator.registry import get_registry


def _agents(subs: List[SubTask]) -> List[str]:
    return [s.agent for s in subs]


# ── split_clauses ───────────────────────────────────────────────────────────
def test_split_on_word_connectors():
    assert split_clauses("write code and test it") == ["write code", "test it"]
    assert split_clauses("plan it then build it") == ["plan it", "build it"]


def test_split_on_punctuation():
    assert split_clauses("write a parser; run tests") == [
        "write a parser", "run tests"]
    assert split_clauses("a, b, c") == ["a", "b", "c"]


def test_no_split_inside_words():
    # "sand" / "android" / "brand" must NOT be split on the "and" substring.
    assert split_clauses("sand the android brand") == ["sand the android brand"]


def test_single_clause_and_empty():
    assert split_clauses("just one task") == ["just one task"]
    assert split_clauses("") == []
    assert split_clauses("   ") == []
    assert split_clauses(None) == []  # type: ignore[arg-type]


# ── the six required cases ──────────────────────────────────────────────────
def test_simple_request_is_one_subtask():
    subs = decompose("write a sum function")
    assert _agents(subs) == ["coder"]
    assert subs[0].request == "write a sum function"


def test_compound_request_splits_per_agent():
    subs = decompose("write a sum function and test it")
    assert _agents(subs) == ["coder", "tester"]
    assert subs[0].request == "write a sum function"
    assert subs[1].request == "test it"


def test_empty_request_yields_no_subtasks():
    assert decompose("") == []
    assert decompose("   ") == []


def test_unknown_clause_falls_back_to_the_router():
    # "frobnicate" is in no lexicon entry → routed by the legacy keyword router.
    subs = decompose("frobnicate the widget")
    assert len(subs) == 1
    assert subs[0].agent in {s.name for s in get_registry().all()}


def test_injected_router_is_used_for_unknown_clauses():
    seen = []

    def fake_router(clause, *, registry=None, genome=None):
        seen.append(clause)
        return "researcher"

    subs = decompose("frobnicate the widget", router=fake_router)
    assert seen == ["frobnicate the widget"]
    assert _agents(subs) == ["researcher"]


def test_a_broken_router_degrades_to_coder():
    def boom(clause, *, registry=None, genome=None):
        raise RuntimeError("router down")

    subs = decompose("frobnicate the widget", router=boom)
    assert _agents(subs) == ["coder"]


def test_many_clauses_preserve_order():
    subs = decompose("plan the work and write the code and test it and "
                     "review it and deploy it")
    assert _agents(subs) == ["planner", "coder", "tester", "reviewer", "devops"]


def test_subtask_priority_high_beats_low():
    # Risk is computed per-subtask, not for the whole request:
    # "delete ..." is HIGH, "add comment to foo" is the exact LOW substring.
    subs = decompose("delete the auth token and add comment to foo")
    risks = [s.risk.value for s in subs]
    assert "high" in risks and "low" in risks
    # the whole request is HIGH (a high pattern appears anywhere) — proving the
    # per-subtask split is finer than the single-request classifier.
    from src.orchestrator.risk import classify as _classify
    assert _classify("delete the auth token and add comment to foo").value == "high"


# ── dedupe / wording ────────────────────────────────────────────────────────
def test_same_agent_dedupes_to_one_subtask():
    subs = decompose("write tests and run tests")
    # both clauses map to tester → a single job (first clause kept)
    assert _agents(subs) == ["tester"]


def test_clause_wording_wins_over_router():
    # "document" is not a strong router keyword but is an explicit verb.
    subs = decompose("document the parser")
    assert _agents(subs) == ["documentation"]
    assert subs[0].request == "document the parser"


def test_subtask_to_dict_shape():
    sub = decompose("write a sum function")[0]
    assert sub.to_dict() == {
        "agent": "coder", "request": "write a sum function", "risk": "med"}


# ── merge_outputs ───────────────────────────────────────────────────────────
def test_merge_outputs_heads_each_section_in_order():
    subs = decompose("write a sum function and test it")
    merged = merge_outputs(subs, [{"output": "def f():\n    pass"}, {}])
    assert "### write — coder" in merged
    assert "### test — tester" in merged
    assert "def f():" in merged
    assert "_(no output)_" in merged  # missing output is stated honestly
    assert merged.index("coder") < merged.index("tester")


def test_merge_outputs_tolerates_short_results():
    subs = decompose("write a sum function and test it")
    merged = merge_outputs(subs, [])
    assert merged.count("_(no output)_") == 2


# ── lexicon integrity (catches a typo before it ships) ──────────────────────
def test_every_lexicon_agent_exists_in_the_registry():
    known = {s.name for s in get_registry().all()}
    for agent, _phrases in _LEXICON:
        assert agent in known, f"unknown agent id in lexicon: {agent}"


def test_lexicon_has_no_duplicate_agents():
    ids = [agent for agent, _ in _LEXICON]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("agent", ["coder", "tester", "reviewer", "planner"])
def test_lexicon_verbs_reach_their_agent(agent: str):
    probes = {
        "coder": "write a module",
        "tester": "run the unit tests",
        "reviewer": "review the patch",
        "planner": "plan the roadmap",
    }
    assert decompose(probes[agent])[0].agent == agent
