"""Fail-closed assurance gate tests."""

from __future__ import annotations

import pytest

from src.intelligence import (
    AssuranceVerdict, EvidenceReference, Finding, FindingStatus,
    IntelligenceResult, ResultStatus, Severity, evaluate_assurance,
)


def _evidence() -> EvidenceReference:
    return EvidenceReference(
        evidence_id="ev-1", kind="scan-manifest", locator="reports/scan.json",
        sha256="a" * 64, collected_by="test-scanner",
    )


def _finding(status: FindingStatus = FindingStatus.CONFIRMED) -> Finding:
    return Finding(
        finding_id="finding-1", rule_id="test.rule", severity=Severity.LOW,
        confidence=0.9, summary="A test finding", status=status,
        evidence_ids=("ev-1",),
    )


def _result(
    *, status: ResultStatus = ResultStatus.COMPLETE,
    findings: tuple[Finding, ...] | None = None,
    evidence: tuple[EvidenceReference, ...] | None = None,
) -> IntelligenceResult:
    return IntelligenceResult(
        mission_id="mission-1", run_id="run-1", engine="test-engine",
        target="repo:sample", scope=("src/",), status=status,
        findings=(_finding(),) if findings is None else findings,
        evidence=(_evidence(),) if evidence is None else evidence,
    )


def _verify(_: EvidenceReference) -> bool:
    return True


def test_complete_result_with_verified_evidence_is_assured() -> None:
    decision = evaluate_assurance(
        _result(), authorized_scope=("src/", "tests/"), verify_evidence=_verify
    )
    assert decision.verdict is AssuranceVerdict.ASSURED
    assert decision.accepted is True
    assert decision.verified_evidence_ids == ("ev-1",)


def test_scope_outside_authorization_is_rejected_before_verification() -> None:
    called = False

    def verifier(_: EvidenceReference) -> bool:
        nonlocal called
        called = True
        return True

    decision = evaluate_assurance(
        _result(), authorized_scope=("docs/",), verify_evidence=verifier
    )
    assert decision.verdict is AssuranceVerdict.REJECTED
    assert called is False


def test_empty_authorized_scope_is_rejected() -> None:
    decision = evaluate_assurance(
        _result(), authorized_scope=(), verify_evidence=_verify
    )
    assert decision.verdict is AssuranceVerdict.REJECTED


def test_missing_evidence_is_rejected() -> None:
    decision = evaluate_assurance(
        _result(evidence=(), findings=()), authorized_scope=("src/",), verify_evidence=_verify
    )
    assert decision.verdict is AssuranceVerdict.REJECTED
    assert "no verifiable evidence" in decision.reasons[0]


@pytest.mark.parametrize("verification", [False, None, 1, "true"])
def test_only_literal_true_verifies_evidence(verification: object) -> None:
    decision = evaluate_assurance(
        _result(), authorized_scope=("src/",),
        verify_evidence=lambda _: verification,  # type: ignore[arg-type]
    )
    assert decision.verdict is AssuranceVerdict.REJECTED


def test_verifier_exception_fails_closed() -> None:
    def broken(_: EvidenceReference) -> bool:
        raise RuntimeError("storage unavailable")

    decision = evaluate_assurance(
        _result(), authorized_scope=("src/",), verify_evidence=broken
    )
    assert decision.verdict is AssuranceVerdict.REJECTED


def test_partial_result_requires_human_review_even_with_valid_evidence() -> None:
    decision = evaluate_assurance(
        _result(status=ResultStatus.PARTIAL),
        authorized_scope=("src/",), verify_evidence=_verify,
    )
    assert decision.verdict is AssuranceVerdict.NEEDS_HUMAN


@pytest.mark.parametrize(
    "finding_status", [FindingStatus.CANDIDATE, FindingStatus.INCONCLUSIVE]
)
def test_unresolved_findings_require_human_review(
    finding_status: FindingStatus,
) -> None:
    decision = evaluate_assurance(
        _result(findings=(_finding(finding_status),)),
        authorized_scope=("src/",), verify_evidence=_verify,
    )
    assert decision.verdict is AssuranceVerdict.NEEDS_HUMAN


@pytest.mark.parametrize("status", [ResultStatus.REJECTED, ResultStatus.FAILED])
def test_failed_or_rejected_engine_result_is_rejected(status: ResultStatus) -> None:
    decision = evaluate_assurance(
        _result(status=status), authorized_scope=("src/",), verify_evidence=_verify
    )
    assert decision.verdict is AssuranceVerdict.REJECTED


def test_missing_verifier_is_rejected() -> None:
    decision = evaluate_assurance(
        _result(), authorized_scope=("src/",),
        verify_evidence=None,  # type: ignore[arg-type]
    )
    assert decision.verdict is AssuranceVerdict.REJECTED


def test_decision_serialization_is_machine_readable() -> None:
    decision = evaluate_assurance(
        _result(), authorized_scope=("src/",), verify_evidence=_verify
    )
    assert decision.to_dict() == {
        "verdict": "assured", "accepted": True,
        "reasons": ["all evidence references verified"],
        "verified_evidence_ids": ["ev-1"],
    }
