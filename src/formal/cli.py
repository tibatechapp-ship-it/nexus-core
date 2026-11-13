"""CLI الطبقة الشكلية — أكواد خروج صادقة مثل MIZAN تماماً.

  * ``0`` — قبول: الحاكم الشكلي أثبت الادعاء داخل الميزانية.
  * ``1`` — رفض: الحاكم أثبت العكس، والدليل (المثال المضاد/الأثر) مطبوع.
  * ``2`` — تعذّر التحقق: ميزانية أو مواصفة غائبة المعنى — لا قبول ولا
    رفض، والسبب مكتوب.

الأمثلة المدمجة هي نماذج عرض حقيقية قابلة للتحقق بأمر واحد؛ الواجهة
البرمجية هي السطح الكامل (الدوال الحاكمية لا تُسلسل JSON بعقدة).
"""

from __future__ import annotations

import argparse
import sys

from src.formal.contract_checker import Contract, InputSpace, check_contract
from src.formal.model_checker import (
    SafetyInvariant,
    StabilityGoal,
    check_system,
    handoff_protocol_demo,
)
from src.formal.prover_loop import StaticGenerator, run_prover_loop
from src.formal.judge import PredicateJudge, VerdictKind

EXIT_ACCEPT = 0
EXIT_REJECT = 1
EXIT_UNKNOWN = 2


def _exit_for(kind: VerdictKind) -> int:
    if kind is VerdictKind.ACCEPT:
        return EXIT_ACCEPT
    if kind is VerdictKind.REJECT:
        return EXIT_REJECT
    return EXIT_UNKNOWN


def _print_verdict(kind: VerdictKind, claim: str, reason: str, judge: str, evidence: tuple[str, ...]) -> None:
    tag = {VerdictKind.ACCEPT: "ACCEPT", VerdictKind.REJECT: "REJECT", VerdictKind.UNKNOWN: "COULD-NOT-VERIFY"}[kind]
    print(f"[{judge}] {tag}: {claim}")
    print(f"  reason: {reason}")
    for line in evidence:
        print(f"  - {line}")


def cmd_model(max_states: int, max_depth: int, breaking: bool) -> int:
    """افحص بروتوكول تسليم العرض — أو نسخة معطوبة عمداً لرؤية الرفض بأثره."""
    system = handoff_protocol_demo()
    token_never_lost: SafetyInvariant[tuple[str, bool]] = SafetyInvariant(
        name="token-never-lost",
        predicate=lambda s: s[0] in ("agent-a", "agent-b"),
    )
    if breaking:
        def successors(state: tuple[str, bool]) -> tuple[tuple[str, bool], ...]:
            holder, escalated = state
            return ((holder, True), ("agent-c", escalated))  # رمز يضيع في وكيل ثالث

        from src.formal.model_checker import TransitionSystem
        system = TransitionSystem(
            name="two-agent-handoff-breaking",
            initial_states=(("agent-a", False),),
            successors=successors,
        )
    report = check_system(
        system,
        invariants=(token_never_lost,),
        goals=(StabilityGoal(name="handoff-completes", goal=lambda s: s[1], bound=4),),
        max_states=max_states,
        max_depth=max_depth,
    )
    _print_verdict(
        report.verdict.kind, report.verdict.claim,
        report.verdict.reason, report.verdict.judge,
        (f"explored={report.explored_states} depth={report.max_depth_reached}",),
    )
    if report.counterexample_trace:
        print(f"  counterexample trace: {report.counterexample_trace}")
    return _exit_for(report.verdict.kind)


def cmd_contract() -> int:
    """عقد عرض: قسيمة آمنة — لا قسمة على صفر، والناتج صحيح مقابل الضرب."""
    def safe_div(numerator: int, denominator: int) -> int:
        return numerator // denominator

    contract = Contract(
        name="safe-div-roundtrip",
        description="n // d تُعاد ضربها فترجع إلى n أو إلى n-1 (بلا استثناء)",
        ensures=(
            lambda n, d, result: n // d == result,  # noqa: ARG005 — العقد نفسه
        ),
    )
    space = InputSpace(
        candidates=tuple(
            (n, d)
            for n in range(0, 8)
            for d in range(1, 4)  # المجال يستبعد d=0 عمداً — وواضح في requires
        ),
        label="8x3 grid, nonzero divisor",
    )
    report = check_contract(safe_div, contract, space, max_cases=64)
    _print_verdict(
        report.verdict.kind, report.verdict.claim,
        report.verdict.reason, report.verdict.judge, (),
    )
    if report.failing_input is not None:
        print(f"  counterexample: input={report.failing_input!r} result={report.failing_result!r}")
    return _exit_for(report.verdict.kind)


def cmd_loop(broken: bool) -> int:
    """حلقة عرض: مولّد يبحث عن قيمة تمر المسند — والحاكم وحده يقبل."""
    predicate_judge = PredicateJudge(
        predicate=lambda c: c == 42 and not broken,
        claim="candidate is the verified answer (42)",
    )
    generator = StaticGenerator(candidates=(1, 17, 42) if not broken else (1, 17, 99))
    report = run_prover_loop(
        claim="candidate is the verified answer (42)",
        judge=predicate_judge,
        generator=generator,
        max_attempts=5,
    )
    _print_verdict(
        report.verdict.kind, report.verdict.claim,
        report.verdict.reason, report.verdict.judge,
        report.evidence_lines(),
    )
    return _exit_for(report.verdict.kind)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="src.formal",
        description=(
            "formal judges: exit 0 accept / 1 reject / 2 could-not-verify "
            "(same honest contract as MIZAN)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    model_cmd = sub.add_parser("model", help="bounded state-machine model check (TLA+/TLC analogue)")
    model_cmd.add_argument("--max-states", type=int, default=10_000)
    model_cmd.add_argument("--max-depth", type=int, default=10_000)
    model_cmd.add_argument("--breaking", action="store_true", help="run the deliberately broken protocol — see the full counterexample trace")

    sub.add_parser("contract", help="bounded contract check on a pure function (Dafny analogue)")

    loop_cmd = sub.add_parser("loop", help="propose→verify→repair→terminate loop (AlphaProof-Nexus analogue)")
    loop_cmd.add_argument("--broken", action="store_true", help="no candidate can satisfy the judge — budget exhausts to UNKNOWN")

    args = parser.parse_args(argv)
    if args.command == "model":
        return cmd_model(args.max_states, args.max_depth, args.breaking)
    if args.command == "contract":
        return cmd_contract()
    return cmd_loop(args.broken)


if __name__ == "__main__":
    sys.exit(main())
