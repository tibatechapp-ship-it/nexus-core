"""اختبارات حلقة الإثبات الوكيلية — نمط AlphaProof Nexus الصادق.

العقود المستهدفة:
  * قبول = الحاكم وحده قبل، والسجل كامل بلا انتقاء.
  * الإصلاح موجّه بالدليل: المصلح يرى المرشح المرفوض والمثال المضاد.
  * استنفاد المولّد = UNKNOWN سبب مكتوب (لا قبول مريح).
  * نفاد الميزانية = UNKNOWN؛ ميزانية صفر مرفوضة بنائياً.
  * فشل المولّد باستثناء = UNKNOWN صاخب.
  * حاكم يعيد UNKNOWN يوقف الحلقة فوراً — لا محاولات إضافية.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.formal.judge import PredicateJudge, Verdict, VerdictKind
from src.formal.prover_loop import (
    Attempt,
    CounterexampleGuidedGenerator,
    Generator,
    StaticGenerator,
    loop_verdict_or_raise,
    run_prover_loop,
)


def test_accept_on_first_candidate() -> None:
    judge = PredicateJudge(predicate=lambda c: c == 42, claim="answer")
    report = run_prover_loop("answer", judge, StaticGenerator(candidates=(42,)))
    assert report.accepted
    assert len(report.attempts) == 1
    assert report.stopped_because == "accepted"
    assert loop_verdict_or_raise(report).accepted


def test_counterexample_guided_repair_sees_verdict_evidence() -> None:
    seen: list[tuple[Any, Verdict]] = []

    def repair(candidate: Any, verdict: Verdict) -> Any:
        seen.append((candidate, verdict))
        return 42  # الإصلاح المدروس بعد رؤية الدليل

    judge = PredicateJudge(predicate=lambda c: c == 42, claim="answer")
    generator = CounterexampleGuidedGenerator(initial=17, repair=repair)
    report = run_prover_loop("answer", judge, generator)
    assert report.accepted
    assert len(seen) == 1
    assert seen[0][0] == 17
    assert seen[0][1].counterexample == 17  # الدليل وصل المصحّح كما هو


def test_generator_exhaustion_is_unknown_not_accept() -> None:
    judge = PredicateJudge(predicate=lambda c: False, claim="impossible")
    report = run_prover_loop("impossible", judge, StaticGenerator(candidates=(1, 2)))
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "generator exhausted" in report.stopped_because
    assert len(report.attempts) == 2  # كل محاولة سُجّلت كما هي


def test_budget_exhaustion_is_unknown() -> None:
    judge = PredicateJudge(predicate=lambda c: c == 99, claim="99")
    generator = StaticGenerator(candidates=(1, 2, 3, 4, 5, 6))
    report = run_prover_loop("99", judge, generator, max_attempts=3)
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "budget exhausted (3)" in report.stopped_because
    assert len(report.attempts) == 3


def test_zero_budget_rejected_at_construction() -> None:
    judge = PredicateJudge(predicate=lambda c: True, claim="c")
    with pytest.raises(ValueError):
        run_prover_loop("c", judge, StaticGenerator(candidates=(1,)), max_attempts=0)


def test_generator_crash_is_unknown() -> None:
    class BoomGenerator(Generator):
        name = "boom"

        def propose(self, claim: str, history: tuple[Attempt, ...]) -> Any:
            raise RuntimeError("generator broke")

    judge = PredicateJudge(predicate=lambda c: True, claim="c")
    report = run_prover_loop("c", judge, BoomGenerator())
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "generator broke" in report.stopped_because
    assert report.attempts == ()


def test_unknown_verdict_stops_the_loop_immediately() -> None:
    def unknown_predicate(candidate: Any) -> bool:
        raise RuntimeError("cannot evaluate")

    judge = PredicateJudge(predicate=unknown_predicate, claim="c")
    generator = StaticGenerator(candidates=(1, 2, 3))
    report = run_prover_loop("c", judge, generator)
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "could not verify" in report.stopped_because
    assert len(report.attempts) == 1


def test_loop_verdict_or_raise_raises_on_failure() -> None:
    judge = PredicateJudge(predicate=lambda c: False, claim="never")
    report = run_prover_loop("never", judge, StaticGenerator(candidates=(1,)), max_attempts=1)
    with pytest.raises(Exception):
        loop_verdict_or_raise(report)


def test_evidence_lines_full_history() -> None:
    judge = PredicateJudge(predicate=lambda c: c == 42, claim="answer")
    report = run_prover_loop(
        "answer", judge, StaticGenerator(candidates=(1, 42))
    )
    lines = report.evidence_lines()
    assert len(lines) == 2
    assert "#1 [static] reject" in lines[0]
    assert "counterexample: 1" in lines[0]
    assert "#2 [static] accept" in lines[1]


def test_static_generator_returns_none_after_list() -> None:
    generator = StaticGenerator(candidates=(1,))
    assert generator.propose("c", ()) == 1
    past = (Attempt(1, "static", 1, Verdict(VerdictKind.REJECT, "c", "r", "j")),)
    assert generator.propose("c", past) is None
