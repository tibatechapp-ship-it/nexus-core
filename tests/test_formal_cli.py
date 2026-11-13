"""اختبارات CLI الطبقة الشكلية — أكواد الخروج الصادقة (0/1/2) والنصوص.

العقود المستهدفة:
  * model: قبول البروتوكول الصحيح (0) ورفض النسخة المعطوبة بأثر كامل (1).
  * contract: قبول عقد القسمة الآمنة (0).
  * loop: قبول (0)؛ --broken → نفاد الميزانية UNKNOWN (2).
  * الخريطة نفسها لدى MIZAN: 0 قبول / 1 رفض / 2 تعذّر التحقق.
  * raise_if_rejected يرفع بالدليل.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.formal.cli import EXIT_ACCEPT, EXIT_REJECT, EXIT_UNKNOWN, main
from src.formal.judge import FormalRejection, PredicateJudge, Verdict, VerdictKind


def test_model_accepts_the_honest_protocol(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["model"])
    out = capsys.readouterr().out
    assert code == EXIT_ACCEPT
    assert "ACCEPT" in out
    assert "bounded" in out


def test_model_breaking_rejects_with_counterexample_trace(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["model", "--breaking"])
    out = capsys.readouterr().out
    assert code == EXIT_REJECT
    assert "REJECT" in out
    assert "counterexample trace" in out
    assert "agent-c" in out  # الأثر يصل لحالة التسريب نفسها


def test_contract_command_accepts(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["contract"])
    out = capsys.readouterr().out
    assert code == EXIT_ACCEPT
    assert "safe-div-roundtrip" in out


def test_loop_accepts_within_budget(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["loop"])
    assert code == EXIT_ACCEPT


def test_loop_broken_exhausts_budget_to_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["loop", "--broken"])
    out = capsys.readouterr().out
    assert code == EXIT_UNKNOWN
    assert "COULD-NOT-VERIFY" in out
    # ثمانية مرشحين في العرض المعطوب: المولّد يستنفد قبل الميزانية
    assert "generator exhausted" in out


def test_exit_code_constants_match_the_mizan_contract() -> None:
    assert EXIT_ACCEPT == 0
    assert EXIT_REJECT == 1
    assert EXIT_UNKNOWN == 2


def test_verdict_raise_if_rejected_carries_evidence() -> None:
    verdict = Verdict(
        kind=VerdictKind.REJECT,
        claim="invariant holds",
        reason="violated",
        judge="model-checker",
        counterexample=("agent-a", False),
    )
    with pytest.raises(FormalRejection) as excinfo:
        verdict.raise_if_rejected()
    assert "model-checker" in str(excinfo.value)
    assert "counterexample: ('agent-a', False)" in str(excinfo.value)


def test_verdict_raise_if_rejected_silent_on_accept() -> None:
    verdict = Verdict(
        kind=VerdictKind.ACCEPT,
        claim="invariant holds",
        reason="exhaustive",
        judge="model-checker",
    )
    verdict.raise_if_rejected()  # لا يرفع — القبول يتقدم كما هو


def test_predicate_judge_defaults_are_honest() -> None:
    judge = PredicateJudge(predicate=lambda c: True)
    verdict = judge.judge("candidate satisfies predicate", 1)
    assert verdict.claim == "candidate satisfies predicate"
    assert verdict.accepted
