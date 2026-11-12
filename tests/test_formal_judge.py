"""اختبارات عقد الحاكم — «المُقترح يبحث، والحاكم يحكم».

العقود المستهدفة:
  * الحكم ثلاثي صريح، وفشل تقييم المسند UNKNOWN لا قبول ولا رفض.
  * require_accept/raise_if_rejected صاخبة مع الدليل.
  * التركيب: UNKNOWN معدٍ، وأول رفض يُمرر باسم حاكمه.
  * الحاكم حتمي ونقي: نفس المدخل → نفس الحكم.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.formal.judge import (
    FormalRejection,
    PredicateJudge,
    Verdict,
    VerdictKind,
    all_accept,
    evidence_lines,
)


def test_predicate_accept_carries_judge_name() -> None:
    judge = PredicateJudge(predicate=lambda c: c == 42, claim="answer is 42")
    verdict = judge.judge("answer is 42", 42)
    assert verdict.kind is VerdictKind.ACCEPT
    assert verdict.judge == "predicate-judge"
    assert verdict.accepted


def test_predicate_reject_carries_candidate_as_counterexample() -> None:
    judge = PredicateJudge(predicate=lambda c: c == 42, claim="answer is 42")
    verdict = judge.judge("answer is 42", 41)
    assert verdict.kind is VerdictKind.REJECT
    assert verdict.counterexample == 41
    assert verdict.rejected


def test_predicate_failure_is_unknown_never_accept() -> None:
    def boom(candidate: Any) -> bool:
        raise RuntimeError("cannot evaluate")

    judge = PredicateJudge(predicate=boom, claim="x")
    verdict = judge.judge("x", 7)
    assert verdict.kind is VerdictKind.UNKNOWN
    assert "cannot evaluate" in verdict.reason


def test_require_accept_raises_with_evidence() -> None:
    verdict = Verdict(
        kind=VerdictKind.REJECT,
        claim="c",
        reason="bad",
        judge="j",
        counterexample=(1, 2),
    )
    with pytest.raises(FormalRejection) as excinfo:
        verdict.require_accept()
    assert "counterexample=(1, 2)" in str(excinfo.value)


def test_unknown_never_passes_the_gate() -> None:
    verdict = Verdict(kind=VerdictKind.UNKNOWN, claim="c", reason="budget", judge="j")
    with pytest.raises(FormalRejection):
        verdict.require_accept()


def test_all_accept_empty_is_unknown() -> None:
    verdict = all_accept([])
    assert verdict.kind is VerdictKind.UNKNOWN
    assert "cannot certify" in verdict.reason


def test_all_accept_first_reject_wins_with_its_judge() -> None:
    reject = Verdict(kind=VerdictKind.REJECT, claim="a", reason="r1", judge="judge-a", counterexample="ce")
    accept = Verdict(kind=VerdictKind.ACCEPT, claim="b", reason="ok", judge="judge-b")
    composed = all_accept([accept, reject])
    assert composed.kind is VerdictKind.REJECT
    assert composed.judge == "judge-a"
    assert composed.counterexample == "ce"


def test_all_accept_unknown_is_contagious() -> None:
    accept = Verdict(kind=VerdictKind.ACCEPT, claim="a", reason="ok", judge="a")
    unknown = Verdict(kind=VerdictKind.UNKNOWN, claim="b", reason="budget", judge="b")
    assert all_accept([accept, unknown]).kind is VerdictKind.UNKNOWN


def test_all_accept_full_pass() -> None:
    verdicts = [
        Verdict(kind=VerdictKind.ACCEPT, claim="a", reason="ok", judge="a"),
        Verdict(kind=VerdictKind.ACCEPT, claim="b", reason="ok", judge="b"),
    ]
    composed = all_accept(verdicts)
    assert composed.kind is VerdictKind.ACCEPT
    assert "2 judge(s)" in composed.reason


def test_judge_is_deterministic_and_pure() -> None:
    judge = PredicateJudge(predicate=lambda c: c > 0, claim="positive")
    first = judge.judge("positive", 5)
    second = judge.judge("positive", 5)
    assert first == second
    assert judge.judge("positive", -1).kind is VerdictKind.REJECT


def test_evidence_lines_render_counterexample() -> None:
    lines = evidence_lines(
        [
            Verdict(
                kind=VerdictKind.REJECT,
                claim="c",
                reason="r",
                judge="j",
                counterexample=3,
            )
        ]
    )
    assert lines == ("[j] reject: c — r | counterexample: 3",)
