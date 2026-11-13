"""اختبارات فاحص النماذج المحدود — مستوى TLA+/TLC الصادق.

العقود المستهدفة:
  * سلامة: مخالفة = REJECT بأثر خالق كامل من الابتداء للمخالفة.
  * ميزانية مكسورة = UNKNOWN صريح (لا «سليم» عن ما لم يُعرف).
  * استقرار محدود: مسار فاشل كامل عند الرفض؛ هدف مبكر يقطع الغصن.
  * لا متغيرات ولا أهداف = UNKNOWN (لا قبول فارغ).
  * الحاكم حتمي: نفس النموذج يعطي نفس الأثر حرفياً.
  * نظام بلا حالات ابتدائية مرفوض بنائياً.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.formal.model_checker import (
    SafetyInvariant,
    StabilityGoal,
    TransitionSystem,
    check_safety,
    check_stability,
    check_system,
    handoff_protocol_demo,
)
from src.formal.judge import VerdictKind

State = tuple[str, bool]


def _good_successors(state: State) -> Iterator[State]:
    holder, escalated = state
    yield (holder, True)
    yield ("agent-b" if holder == "agent-a" else "agent-a", escalated)


def test_safety_violation_carries_full_creator_trace() -> None:
    def leaking_successors(state: State) -> Iterator[State]:
        holder, escalated = state
        yield (holder, True)
        yield ("agent-b" if holder == "agent-a" else "agent-a", escalated)
        yield ("agent-c", escalated)  # التسريب: رمز يذهب لوكيل خارج النظام

    system = TransitionSystem(
        name="leaky",
        initial_states=(("agent-a", False),),
        successors=leaking_successors,
    )
    report = check_safety(
        system,
        (SafetyInvariant(name="known-holders", predicate=lambda s: s[0] in ("agent-a", "agent-b")),),
    )
    assert report.verdict.kind is VerdictKind.REJECT
    assert report.violated_invariant == "known-holders"
    trace = report.counterexample_trace
    assert trace, "a rejection must carry the counterexample trace"
    assert trace[0] == ("agent-a", False), "trace must start at an initial state"
    assert trace[-1][0] == "agent-c", "trace must end at the violating state"


def test_safety_pass_exhaustive_within_budget() -> None:
    system = handoff_protocol_demo()
    report = check_safety(
        system,
        (SafetyInvariant(name="holder-known", predicate=lambda s: s[0] in ("agent-a", "agent-b")),),
    )
    assert report.verdict.kind is VerdictKind.ACCEPT
    # القابلة للوصول: (a,False) → (a,True),(b,True) — أهذا ثلاث حالات
    assert report.explored_states == 3
    assert "bounded proof" in report.verdict.reason


def test_budget_exceeded_is_unknown_not_accept() -> None:
    def infinite(state: State) -> Iterator[State]:
        n = int(state[0]) if state[0].isdigit() else 0
        yield (str(n + 1), False)

    system = TransitionSystem(
        name="unbounded",
        initial_states=(("0", False),),
        successors=infinite,
    )
    report = check_safety(
        system,
        (SafetyInvariant(name="always-true", predicate=lambda s: True),),
        max_states=50,
    )
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert report.budget_exceeded
    assert "budget exceeded" in report.verdict.reason


def test_bound_over_depth_budget_is_unknown() -> None:
    system = handoff_protocol_demo()
    report = check_stability(
        system,
        StabilityGoal(name="escalated", goal=lambda s: s[1], bound=100),
        max_depth=50,
    )
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert report.budget_exceeded
    assert "exceeds the depth budget" in report.verdict.reason


def test_no_invariants_is_unknown_not_accept() -> None:
    system = handoff_protocol_demo()
    report = check_safety(system, ())
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "nothing to verify" in report.verdict.reason


def test_empty_initial_states_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        TransitionSystem(name="empty", initial_states=(), successors=_good_successors)


def test_stability_reject_carries_failing_path() -> None:
    system = TransitionSystem(
        name="never-goal",
        initial_states=(("agent-a", False),),
        successors=lambda s: (s,),  # حلقة سرمائية لا تصل أبداً — الحلقات تُحترم
    )
    report = check_stability(system, StabilityGoal(name="done", goal=lambda s: s[1], bound=3))
    assert report.verdict.kind is VerdictKind.REJECT
    assert report.failed_goal == "done"
    assert len(report.counterexample_trace) == 4  # البداية + 3 خطوات
    assert "cycles are honoured" in report.verdict.reason


def test_dead_end_path_also_rejects() -> None:
    system = TransitionSystem(
        name="dead-end",
        initial_states=(("agent-a", False),),
        successors=lambda s: (),  # لا خلفاء والمديف لم يبلغ
    )
    report = check_stability(system, StabilityGoal(name="done", goal=lambda s: s[1], bound=2))
    assert report.verdict.kind is VerdictKind.REJECT
    # المسار الفاشل هو الحالة الوحيدة نفسها: صفر خطوات ممكنة أصلاً
    assert report.counterexample_trace == (("agent-a", False),)
    assert report.verdict.evidence["failing_path_length"] == 0


def test_stability_goal_cut_prunes_branches() -> None:
    system = handoff_protocol_demo()
    report = check_stability(system, StabilityGoal(name="escalated", goal=lambda s: s[1], bound=4))
    assert report.verdict.kind is VerdictKind.ACCEPT
    # الأزواج المُحسوبة تتناقص مع الهدف — الحالات الفعلية ثلاثة:
    # (a,False),(a,True),(b,True): الهدف يقطع كل غصن عند بلوغه
    assert report.explored_states == 3
    assert report.max_depth_reached == 4


def test_stability_rejects_non_escalating_cycle() -> None:
    # النظام المتساهل القديم: تسليم دون رفع مسموح → حلقة a→b→a→b
    # لا ترتقي أبداً — الفاحص الصادق يرفضها بأثرها الكامل (دليل
    # أن تقصُّ الزيارات الصامت كان سيقبل زوراً).
    system = TransitionSystem(
        name="permissive-handoff",
        initial_states=(("agent-a", False),),
        successors=_good_successors,
    )
    report = check_stability(system, StabilityGoal(name="escalated", goal=lambda s: s[1], bound=4))
    assert report.verdict.kind is VerdictKind.REJECT
    trace = report.counterexample_trace
    assert trace[0] == ("agent-a", False)
    assert trace[-1] == ("agent-a", False)  # عاد لنقطة البداية دون رفع


def test_stability_bound_must_be_positive() -> None:
    with pytest.raises(ValueError):
        StabilityGoal(name="bad", goal=lambda s: True, bound=0)


def test_check_system_worst_verdict_wins() -> None:
    system = handoff_protocol_demo()
    good = check_system(
        system,
        invariants=(SafetyInvariant(name="i1", predicate=lambda s: s[0] in ("agent-a", "agent-b")),),
        goals=(StabilityGoal(name="g1", goal=lambda s: s[1], bound=4),),
    )
    assert good.verdict.kind is VerdictKind.ACCEPT

    broken = check_system(
        system,
        invariants=(SafetyInvariant(name="i2", predicate=lambda s: False),),
    )
    assert broken.verdict.kind is VerdictKind.REJECT
    assert broken.violated_invariant == "i2"


def test_check_system_with_nothing_declared_is_unknown() -> None:
    report = check_system(handoff_protocol_demo())
    assert report.verdict.kind is VerdictKind.UNKNOWN


def test_check_system_unknown_budget_contagion() -> None:
    def counter(state: State) -> Iterator[State]:
        n = int(state[0])
        yield (str(n + 1), n + 1 >= 3)

    system = TransitionSystem(name="counter", initial_states=(("0", False),), successors=counter)
    report = check_system(
        system,
        invariants=(SafetyInvariant(name="ok", predicate=lambda s: True),),
        goals=(StabilityGoal(name="reached", goal=lambda s: s[1], bound=8),),
        max_states=3,  # ميزانية أصغر من سلسلة العدّاد اللازمة للحكم
    )
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert report.budget_exceeded
    assert "budget exceeded" in report.verdict.reason


def test_determinism_same_model_same_trace() -> None:
    system = TransitionSystem(
        name="leaky",
        initial_states=(("agent-a", False),),
        successors=_good_successors,
    )
    inv = (SafetyInvariant(name="known", predicate=lambda s: s[0] in ("agent-a", "agent-b")),)
    first = check_safety(system, inv)
    second = check_safety(system, inv)
    assert first.counterexample_trace == second.counterexample_trace
    assert first.verdict == second.verdict


def test_invariant_predicate_failure_is_unknown() -> None:
    def boom(state: State) -> bool:
        raise ValueError("bad predicate")

    system = handoff_protocol_demo()
    report = check_safety(system, (SafetyInvariant(name="boom", predicate=boom),))
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "bad predicate" in report.verdict.reason
