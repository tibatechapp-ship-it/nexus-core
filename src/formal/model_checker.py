"""فاحص النماذج المحدود — المكافئ الصادق لمستوى TLA+/TLC.

إعادة هندسة عكسية: نأخذ **جوهر** TLC (تعداد حالات صريح + متغيرات
سلامة + أثر مخالفة قابل للقراءة) بلا ادعاء غير محدود:

  * التحقق هنا **محدود بميزانيتين معلنتين**: ``max_states`` و
    ``max_depth``. تجاوز أي منهما ينتج ``UNKNOWN`` بسبب مكتوب —
    ليس قبولاً ولا رفضاً.
  * متغيرات السلامة (safety): «كل حالة قابلة للوصول تحقق المسند» —
    رفض يحمل **أثر الخالق الكامل** (سلسلة الحالات من الابتداء للمخالفة).
  * الاستقرار المحدود (bounded stability — أخو liveness الصادق):
    «على كل مسار بطول ≤ bound تنتهي الحالة في الهدف» — رفض يحمل
    أطول مسار فاشل. الاسم يقول «bounded» ولا يقول «liveness
    غير محدود» — هذا حد معلن لا عيب مخفي.

الحاكم حتمي: الترتيب BFS مع قاموس زيارات — نفس النموذج يعطي نفس
الأثر دائماً. لا شبكة، لا ملفات، لا عشوائية.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from src.formal.judge import Verdict, VerdictKind

S = TypeVar("S", bound=Hashable)

DEFAULT_MAX_STATES = 10_000
DEFAULT_MAX_DEPTH = 10_000


@dataclass(frozen=True)
class TransitionSystem(Generic[S]):
    """نظام انتقالات: حالات ابتدائية + دالة خلفاء حتمية-علاقية.

    ``successors`` تعيد حالات الخلف لأي حالة (ترتيبها ثابت؛ التكرار
    مسموح — الفاحص يزيله بالزيارات). الدالة نقية أو نرفض. النظام
    عام على نوع الحالة ``S`` فتبقى الحالات الملموسة مُنمّطة بالكامل.
    """

    name: str
    initial_states: tuple[S, ...]
    successors: Callable[[S], Iterable[S]]

    def __post_init__(self) -> None:
        if not self.initial_states:
            raise ValueError(
                f"transition system {self.name!r}: no initial states — "
                "an empty initial set cannot verify anything (UNKNOWN would lie)"
            )


@dataclass(frozen=True)
class SafetyInvariant(Generic[S]):
    """متغير سلامة: مسند يجب أن يصح في كل حالة قابلة للوصول."""

    name: str
    predicate: Callable[[S], bool]


@dataclass(frozen=True)
class StabilityGoal(Generic[S]):
    """هدف استقرار محدود: كل مسار بطول ≤ bound ينتهي في ``goal``."""

    name: str
    goal: Callable[[S], bool]
    bound: int

    def __post_init__(self) -> None:
        if self.bound <= 0:
            raise ValueError(
                f"stability goal {self.name!r}: bound must be positive"
            )


@dataclass(frozen=True)
class ModelReport:
    """تقرير فحص كامل — الأحكام والأدلة لا الشعور."""

    system: str
    verdict: Verdict
    explored_states: int
    max_depth_reached: int
    violated_invariant: str | None = None
    counterexample_trace: tuple[Hashable, ...] = ()
    failed_goal: str | None = None
    budget_exceeded: bool = False


def _explore(
    system: TransitionSystem[S],
    max_states: int,
    max_depth: int,
) -> tuple[dict[S, int], dict[S, S], bool, bool]:
    """BFS محدود: يعيد (العمق لكل حالة، الأب، علم تجاوز الحالات، علم تجاوز العمق).

    يعيد أيضًا خريطة الأب لبناء أثر الخالق بأقل تكلفة ذاكرة ممكنة.
    """
    depth: dict[S, int] = {}
    parent: dict[S, S] = {}
    queue: deque[tuple[S, int]] = deque()
    states_hit = False
    depth_hit = False
    for state in system.initial_states:
        if state not in depth:
            depth[state] = 0
            queue.append((state, 0))
    while queue:
        state, d = queue.popleft()
        if d >= max_depth:
            depth_hit = True
            continue
        for nxt in system.successors(state):
            if nxt in depth:
                continue
            if len(depth) >= max_states:
                states_hit = True
                return depth, parent, states_hit, depth_hit
            depth[nxt] = d + 1
            parent[nxt] = state
            queue.append((nxt, d + 1))
    return depth, parent, states_hit, depth_hit


def _trace_to(
    state: S,
    parent: dict[S, S],
) -> tuple[S, ...]:
    """أثر من الابتداء إلى الحالة — يُقرأ من المخالفة للأصل ثم يُعكس."""
    path: list[S] = [state]
    while state in parent:
        state = parent[state]
        path.append(state)
    return tuple(reversed(path))


def check_safety(
    system: TransitionSystem[S],
    invariants: Sequence[SafetyInvariant[S]],
    max_states: int = DEFAULT_MAX_STATES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ModelReport:
    """افحص متغيرات السلامة على كل الحالات القابلة للوصول داخل الميزانية.

    العقد: أول مخالفة تفصل الفحص وتحمل أثرها؛ الميزانية المكسورة تنتج
    UNKNOWN (لا يقول «سليم» عن ما لم يبلغه)؛ كل المتغيرات تمر → ACCEPT.
    """
    if not invariants:
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"system {system.name!r} is safe",
                reason="no invariants declared — nothing to verify",
                judge="model-checker",
            ),
            explored_states=0,
            max_depth_reached=0,
        )
    depth, parent, states_hit, depth_hit = _explore(
        system, max_states, max_depth
    )
    explored = len(depth)
    deepest = max(depth.values(), default=0)
    budget = states_hit or depth_hit
    if budget:
        reason = (
            f"budget exceeded before full exploration "
            f"(states={explored}/{max_states}, depth={deepest}/{max_depth})"
        )
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"system {system.name!r} is safe",
                reason=reason,
                judge="model-checker",
                evidence={"explored": explored, "max_states": max_states},
            ),
            explored_states=explored,
            max_depth_reached=deepest,
            budget_exceeded=True,
        )
    for inv in invariants:
        for state in sorted(depth, key=lambda s: depth[s]):
            try:
                holds = bool(inv.predicate(state))
            except Exception as exc:  # noqa: BLE001
                return ModelReport(
                    system=system.name,
                    verdict=Verdict(
                        kind=VerdictKind.UNKNOWN,
                        claim=f"invariant {inv.name!r} holds on all reachable states",
                        reason=f"predicate raised on state {state!r}: {exc!r}",
                        judge="model-checker",
                    ),
                    explored_states=explored,
                    max_depth_reached=deepest,
                )
            if not holds:
                trace = _trace_to(state, parent)
                return ModelReport(
                    system=system.name,
                    verdict=Verdict(
                        kind=VerdictKind.REJECT,
                        claim=f"invariant {inv.name!r} holds on all reachable states",
                        reason=f"violated at state {state!r}",
                        judge="model-checker",
                        counterexample=trace,
                        evidence={"violated_state_depth": depth[state]},
                    ),
                    explored_states=explored,
                    max_depth_reached=deepest,
                    violated_invariant=inv.name,
                    counterexample_trace=trace,
                )
    return ModelReport(
        system=system.name,
        verdict=Verdict(
            kind=VerdictKind.ACCEPT,
            claim=(
                f"all {len(invariants)} invariant(s) hold on all "
                f"{explored} reachable state(s)"
            ),
            reason="exhaustive within budget — bounded proof",
            judge="model-checker",
            evidence={"explored": explored},
        ),
        explored_states=explored,
        max_depth_reached=deepest,
    )


def check_stability(
    system: TransitionSystem[S],
    goal: StabilityGoal[S],
    max_states: int = DEFAULT_MAX_STATES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ModelReport:
    """افحص أن كل مسار بطول ≤ goal.bound ينتهي في الهدف (استقرار محدود).

    الدلالة دقيقة على الحلقات: ``reaches(state, k)`` = «كل مسار بطول
    ≤ k من هذه الحالة يبلغ الهدف» — تُحسب بازدواج محفوظ (memoization)
    بمفتاح ``(الحالة، المتبقي)``؛ الحلقة الراجعة (state → … → state)
    تُكتشف لأن k يتناقص صرامة: ``reaches(s, 0) = goal(s)`` و
    ``reaches(s, k) = goal(s) or all(reaches(t, k-1) for t in successors(s))``.
    المسار السرمائي الدائري الذي لا يلمس الهدف أبداً = رفض بأثر كامل —
    كما يكشفه TLC في liveness، لا تقصُّ صامت بالزيارات.

    الميزانيتان: ``max_states`` (عدد أزواج الحالة/المتبقي المحسوبة)
    و``max_depth`` (سقف bound) — كسرهما UNKNOWN مكتوب لا «سليم».
    """
    if goal.bound > max_depth:
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"system {system.name!r} reaches the goal {goal.name!r}",
                reason=(
                    f"declared bound {goal.bound} exceeds the depth "
                    f"budget {max_depth} — refusing to judge what it "
                    "cannot explore"
                ),
                judge="model-checker",
            ),
            explored_states=0,
            max_depth_reached=0,
            budget_exceeded=True,
        )

    def successors_of(state: S) -> tuple[S, ...] | None:
        try:
            return tuple(system.successors(state))
        except Exception:  # noqa: BLE001 — فشل البناء يُفسَّر لاحقاً لا كطريق مسدود
            return None

    memo: dict[tuple[S, int], bool] = {}
    goal_failure: str | None = None
    stack: list[tuple[S, int]] = [
        (state, goal.bound) for state in system.initial_states
    ]
    while stack:
        if len(memo) > max_states:
            return ModelReport(
                system=system.name,
                verdict=Verdict(
                    kind=VerdictKind.UNKNOWN,
                    claim=f"system {system.name!r} reaches the goal {goal.name!r}",
                    reason=(
                        f"budget exceeded while computing the reachability "
                        f"closure (pairs={len(memo)}/{max_states})"
                    ),
                    judge="model-checker",
                ),
                explored_states=len(memo),
                max_depth_reached=goal.bound,
                budget_exceeded=True,
            )
        state, remaining = stack[-1]
        if (state, remaining) in memo:
            stack.pop()
            continue
        try:
            at_goal = bool(goal.goal(state))
        except Exception as exc:  # noqa: BLE001
            goal_failure = f"goal predicate raised on state {state!r}: {exc!r}"
            break
        if at_goal:
            memo[(state, remaining)] = True
            stack.pop()
            continue
        if remaining == 0:
            memo[(state, remaining)] = False
            stack.pop()
            continue
        successors = successors_of(state)
        if successors is None:
            goal_failure = f"successors() raised on state {state!r}"
            break
        if not successors:
            # طريق مسدود: لا خلفاء والمديف لم يبلغ — مسار فاشل كامل
            memo[(state, remaining)] = False
            stack.pop()
            continue
        pending = [t for t in successors if (t, remaining - 1) not in memo]
        if pending:
            stack.extend((t, remaining - 1) for t in pending)
            continue
        memo[(state, remaining)] = all(
            memo[(t, remaining - 1)] for t in successors
        )
        stack.pop()

    if goal_failure is not None:
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"system {system.name!r} reaches the goal {goal.name!r}",
                reason=goal_failure,
                judge="model-checker",
            ),
            explored_states=len(memo),
            max_depth_reached=goal.bound,
        )
    if len(memo) > max_states:
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"system {system.name!r} reaches the goal {goal.name!r}",
                reason=(
                    f"budget exceeded while computing the reachability "
                    f"closure (pairs={len(memo)}/{max_states})"
                ),
                judge="model-checker",
            ),
            explored_states=len(memo),
            max_depth_reached=goal.bound,
            budget_exceeded=True,
        )

    verdict_true = all(
        memo[(state, goal.bound)] for state in system.initial_states
    )
    if not verdict_true:
        # بناء الأثر: انزل جشعاً خلفاً يفشل دائماً — كل خطوة تُلحق،
        # والطريق المسدود يقف أينما بلغ (لا خطوات عنده أصلاً).
        trace: list[S] = [system.initial_states[0]]
        current = system.initial_states[0]
        remaining = goal.bound
        while not bool(goal.goal(current)) and remaining > 0:
            successors = successors_of(current) or ()
            failing = [t for t in successors if not memo[(t, remaining - 1)]]
            if not failing:
                break  # طريق مسدود: الحالة الحالية هي نهاية المسار الفاشل
            current = failing[0]
            trace.append(current)
            remaining -= 1
        full_trace = tuple(trace)
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.REJECT,
                claim=(
                    f"every path reaches {goal.name!r} within "
                    f"{goal.bound} step(s)"
                ),
                reason=(
                    f"path survived {goal.bound} step(s) without reaching "
                    "the goal (cycles are honoured — no silent pruning)"
                ),
                judge="model-checker",
                counterexample=full_trace,
                evidence={"failing_path_length": len(full_trace) - 1},
            ),
            explored_states=len(memo),
            max_depth_reached=goal.bound,
            failed_goal=goal.name,
            counterexample_trace=full_trace,
        )
    distinct_states = len({state for state, _ in memo})
    return ModelReport(
        system=system.name,
        verdict=Verdict(
            kind=VerdictKind.ACCEPT,
            claim=(
                f"every path reaches {goal.name!r} within {goal.bound} "
                f"step(s) ({distinct_states} state(s) explored)"
            ),
            reason="bounded stability verified exhaustively within budget — cycles honoured",
            judge="model-checker",
            evidence={"explored": distinct_states, "bound": goal.bound},
        ),
        explored_states=distinct_states,
        max_depth_reached=goal.bound,
    )


def check_system(
    system: TransitionSystem[S],
    invariants: Sequence[SafetyInvariant[S]] = (),
    goals: Sequence[StabilityGoal[S]] = (),
    max_states: int = DEFAULT_MAX_STATES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ModelReport:
    """افحص السلامة ثم الأهداف — أسوأ حكم هو الحكم (UNKNOWN معدٍ)."""
    reports: list[ModelReport] = []
    if invariants:
        reports.append(
            check_safety(system, invariants, max_states, max_depth)
        )
    for goal in goals:
        reports.append(
            check_stability(system, goal, max_states, max_depth)
        )
    if not reports:
        return ModelReport(
            system=system.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"system {system.name!r} is verified",
                reason="no invariants and no goals declared — nothing to verify",
                judge="model-checker",
            ),
            explored_states=0,
            max_depth_reached=0,
        )
    worst = reports[0]
    for report in reports[1:]:
        if report.verdict.kind is VerdictKind.REJECT:
            return report
        if report.verdict.kind is VerdictKind.UNKNOWN:
            worst = report
    if worst.verdict.kind is not VerdictKind.ACCEPT:
        return worst
    return ModelReport(
        system=system.name,
        verdict=Verdict(
            kind=VerdictKind.ACCEPT,
            claim=f"system {system.name!r}: safety and goals verified",
            reason="; ".join(r.verdict.reason for r in reports),
            judge="model-checker",
            evidence={"explored": sum(r.explored_states for r in reports)},
        ),
        explored_states=sum(r.explored_states for r in reports),
        max_depth_reached=max(r.max_depth_reached for r in reports),
    )


def handoff_protocol_demo() -> TransitionSystem:
    """نموذج عرض: بروتوكول تسليم مهمة بين وكيلين (مستوى TLA+ مُصغّر).

    الحالات: (حامل_الرمز، رُفِع_للمنسّق؟). القاعدة: الانتقال الوحيد
    هو تسليم الرمز للوكيل الآخر **مع** رفع الطلب للمنسّق (إلزامي)،
    والحامل قد يرفع دون تسليم — فكل مسار يرتقي خلال خطوة واحدة،
    ولا يلمس الرمز أي وكيل ثالث (متغير السلامة). مخالفاتها تُكتشف
    بأثر كامل، والحلقات السرمائية تُحترم في فحص الاستقرار.
    """
    def successors(state: tuple[str, bool]) -> Iterable[tuple[str, bool]]:
        holder, _escalated = state
        # التسليم إلزامي الرفع؛ والرفع دون تسليم مسموح — لا طريق سرمائي
        # يتجاهل الرفع أبداً (كل انتقال ينتج escalated=True).
        yield ("agent-b" if holder == "agent-a" else "agent-a", True)
        yield (holder, True)

    return TransitionSystem[tuple[str, bool]](
        name="two-agent-handoff",
        initial_states=(("agent-a", False),),
        successors=successors,
    )


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_STATES",
    "ModelReport",
    "SafetyInvariant",
    "StabilityGoal",
    "TransitionSystem",
    "check_safety",
    "check_stability",
    "check_system",
    "handoff_protocol_demo",
]
