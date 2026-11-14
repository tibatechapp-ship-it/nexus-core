"""Regression tests for fail-closed vulnerability confirmation."""
from __future__ import annotations

import pytest

from src.security.confirm import (
    CONFIRM_MARKERS,
    PATCH_HINTS,
    VERDICTS,
    Finding,
    Verdict,
    confirm,
    patch_hint,
    probe_for,
)


def make_finding(
    kind: str = "sql_injection",
    code: str = "SELECT * FROM users WHERE id = {}",
) -> Finding:
    return Finding(rule="mizan-taint", path="src/x.py", line=7, kind=kind, code=code)


class ExplodingSandbox:
    """Any invocation is a test failure: confirmation must not run generic code."""

    def __init__(self) -> None:
        self.called = False

    def run_python(self, code: str, stdin: str = "") -> dict:
        self.called = True
        raise AssertionError("generic synthetic probes must never execute")


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="نوع غير معروف"):
        Finding(rule="r", path="p", line=1, kind="crypto_foo")


@pytest.mark.parametrize("kind", sorted(CONFIRM_MARKERS))
def test_legacy_probe_api_fails_loudly(kind: str) -> None:
    with pytest.raises(NotImplementedError, match="تعطيل البروبات الاصطناعية"):
        probe_for(make_finding(kind=kind))


def test_no_sandbox_is_inconclusive() -> None:
    verdict = confirm(make_finding(), None)
    assert verdict.status == "inconclusive"
    assert "لا يوجد صندوق عزل" in verdict.detail


@pytest.mark.parametrize("kind", sorted(CONFIRM_MARKERS))
def test_sandbox_is_never_asked_to_execute_self_confirming_probe(kind: str) -> None:
    sandbox = ExplodingSandbox()
    verdict = confirm(make_finding(kind=kind), sandbox)
    assert verdict.status == "inconclusive"
    assert "مدقّق واعٍ بسياق الهدف" in verdict.detail
    assert sandbox.called is False
    assert verdict.evidence == ""


def test_synthetic_payload_in_source_cannot_confirm_itself() -> None:
    sandbox = ExplodingSandbox()
    finding = make_finding(
        kind="sql_injection",
        code='query = "SELECT * FROM users WHERE id = \' OR \'1\'=\'1"',
    )
    verdict = confirm(finding, sandbox)
    assert verdict.status == "inconclusive"
    assert sandbox.called is False


def test_clean_source_is_not_automatically_refuted() -> None:
    verdict = confirm(make_finding(kind="xss", code="<p>plain text</p>"), ExplodingSandbox())
    assert verdict.status == "inconclusive"
    assert verdict.status != "refuted"


def test_verdict_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="حكم غير معروف"):
        Verdict(status="maybe", detail="unknown")


@pytest.mark.parametrize("kind", sorted(PATCH_HINTS))
def test_patch_hint_declared_for_every_kind(kind: str) -> None:
    assert patch_hint(make_finding(kind=kind)) == PATCH_HINTS[kind]


def test_patch_hint_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="نوع غير معروف"):
        Finding(rule="r", path="p", line=1, kind="nope")


def test_verdict_vocabulary_remains_three_valued() -> None:
    assert VERDICTS == ("confirmed", "refuted", "inconclusive")
