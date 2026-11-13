"""اختبارات فاحص العقود — مستوى Dafny الصادق.

العقود المستهدفة:
  * مخالفة ensures = REJECT بمثال مضاد كامل (المدخل + الناتج).
  * استثناء دالة على مدخل داخل المجال = REJECT (وليس UNKNOWN).
  * مجال عاقر (كل المدخلات خارج requires) = UNKNOWN لا قبول فارغ.
  * اقتطاع المجال بالميزانية = UNKNOWN (عينة ليست يقيناً).
  * شرط مسبق يرفع استثناءً = UNKNOWN؛ شرط لاحق يرفع استثناءً = UNKNOWN.
  * قبول يصرّح بالنمط (bounded-exhaustive / bounded-sampled).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.formal.contract_checker import (
    Contract,
    InputSpace,
    check_contract,
)
from src.formal.judge import VerdictKind


def _div_contract() -> Contract:
    return Contract(
        name="safe-div",
        requires=(lambda n, d: d != 0,),
        ensures=(
            lambda n, d, result: abs(result * d) <= abs(n),  # type: ignore[arg-type,return-value]
        ),
    )


def test_reject_carries_input_and_result() -> None:
    def bad_div(n: int, d: int) -> int:
        return n + 1  # مخالفة صريحة للعقد

    space = InputSpace(candidates=((4, 2), (6, 3)), label="grid")
    report = check_contract(bad_div, _div_contract(), space)
    assert report.verdict.kind is VerdictKind.REJECT
    assert report.failing_input == (4, 2)
    assert report.failing_result == 5


def test_exception_on_in_domain_input_is_reject() -> None:
    def boom(n: int, d: int) -> int:
        raise ZeroDivisionError("unhandled")

    space = InputSpace(candidates=((4, 2),))
    report = check_contract(boom, _div_contract(), space)
    assert report.verdict.kind is VerdictKind.REJECT
    assert "raised" in report.verdict.reason


def test_vacuous_domain_is_unknown_not_accept() -> None:
    contract = Contract(name="never", requires=(lambda x: x < 0,), ensures=(lambda x, r: True,))
    space = InputSpace(candidates=((1,), (2,), (3,)))
    report = check_contract(lambda x: x, contract, space)
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "vacuous" in report.verdict.reason
    assert report.evaluated_cases == 0


def test_truncated_space_is_unknown() -> None:
    contract = Contract(name="always", ensures=(lambda x, r: True,))
    space = InputSpace(candidates=((i,) for i in range(1000)))
    report = check_contract(lambda x: x, contract, space, max_cases=10)
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "truncated" in report.verdict.reason


def test_out_of_domain_inputs_are_skipped_not_judged() -> None:
    contract = _div_contract()
    space = InputSpace(candidates=((4, 0), (6, 2)))  # الأول خارج المجال عمداً
    report = check_contract(lambda n, d: n // d, contract, space)
    assert report.verdict.kind is VerdictKind.ACCEPT
    assert report.skipped_out_of_domain == 1
    assert report.evaluated_cases == 1
    assert "bounded-exhaustive" in report.verdict.reason


def test_sampled_space_is_labelled_bounded_sampled() -> None:
    contract = Contract(name="always", ensures=(lambda x, r: True,))
    space = InputSpace(candidates=((1,), (2,)), sampled=True)
    report = check_contract(lambda x: x, contract, space)
    assert report.verdict.kind is VerdictKind.ACCEPT
    assert "bounded-sampled" in report.verdict.reason


def test_requires_predicate_failure_is_unknown() -> None:
    def boom(x: int) -> bool:
        raise ValueError("bad requires")

    contract = Contract(name="c", requires=(boom,), ensures=(lambda x, r: True,))
    report = check_contract(lambda x: x, contract, InputSpace(candidates=((1,),)))
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "bad requires" in report.verdict.reason


def test_ensures_predicate_failure_is_unknown() -> None:
    def boom(x: int, r: Any) -> bool:
        raise ValueError("bad ensures")

    contract = Contract(name="c", ensures=(boom,))
    report = check_contract(lambda x: x, contract, InputSpace(candidates=((1,),)))
    assert report.verdict.kind is VerdictKind.UNKNOWN
    assert "bad ensures" in report.verdict.reason


def test_contract_without_ensures_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        Contract(name="empty")


def test_multiple_ensures_first_violation_wins() -> None:
    contract = Contract(
        name="two",
        ensures=(
            lambda x, r: r == x,        # يمر
            lambda x, r: r != x,        # يخالف — الرفض هنا
            lambda x, r: False,         # لن يصل
        ),
    )
    report = check_contract(lambda x: x, contract, InputSpace(candidates=((1,),)))
    assert report.verdict.kind is VerdictKind.REJECT
    assert report.failing_input == (1,)
    assert report.failing_result == 1


def test_div_contract_accepts_real_safe_div() -> None:
    contract = Contract(
        name="safe-div-roundtrip",
        requires=(lambda n, d: d > 0,),
        ensures=(lambda n, d, result: abs(result * d) <= abs(n) and abs(result * d) + d > abs(n),),
    )
    space = InputSpace(candidates=tuple((n, d) for n in range(0, 8) for d in range(1, 4)))
    report = check_contract(lambda n, d: n // d, contract, space)
    assert report.verdict.kind is VerdictKind.ACCEPT
    assert report.evaluated_cases == 24
