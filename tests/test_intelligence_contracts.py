"""Contract validation and serialization tests for intelligence results."""

from __future__ import annotations

import math

import pytest

from src.intelligence import (
    CONTRACT_VERSION,
    ContractError,
    EvidenceReference,
    Finding,
    FindingStatus,
    IntelligenceResult,
    ResultStatus,
    Severity,
)


def evidence(**overrides: object) -> EvidenceReference:
    values: dict[str, object] = {
        "evidence_id": "ev-1",
        "kind": "source-location",
        "locator": "src/app.py:12",
        "sha256": "a" * 64,
        "collected_by": "static-scanner",
    }
    values.update(overrides)
    return EvidenceReference(**values)  # type: ignore[arg-type]


def finding(**overrides: object) -> Finding:
    values: dict[str, object] = {
        "finding_id": "finding-1",
        "rule_id": "python.dynamic-eval",
        "severity": Severity.HIGH,
        "confidence": 0.95,
        "summary": "Dynamic evaluation requires review",
        "status": FindingStatus.CONFIRMED,
        "evidence_ids": ("ev-1",),
    }
    values.update(overrides)
    return Finding(**values)  # type: ignore[arg-type]


def result(**overrides: object) -> IntelligenceResult:
    values: dict[str, object] = {
        "mission_id": "mission-1",
        "run_id": "run-1",
        "engine": "security-assessment",
        "target": "repository:example",
        "scope": ("src/",),
        "status": ResultStatus.COMPLETE,
        "findings": (finding(),),
        "evidence": (evidence(),),
        "limitations": ("Heuristic analysis only",),
        "recommendations": ("Review the flagged call",),
    }
    values.update(overrides)
    return IntelligenceResult(**values)  # type: ignore[arg-type]


def test_result_round_trip_preserves_contract_and_references() -> None:
    original = result()
    restored = IntelligenceResult.from_dict(original.to_dict())

    assert restored == original
    assert restored.contract_version == CONTRACT_VERSION
    assert restored.findings[0].evidence_ids == ("ev-1",)
    assert restored.evidence[0].sha256 == "a" * 64


def test_candidate_finding_can_have_no_evidence() -> None:
    item = finding(status=FindingStatus.CANDIDATE, evidence_ids=())
    assert item.status is FindingStatus.CANDIDATE


def test_confirmed_finding_requires_evidence() -> None:
    with pytest.raises(ContractError, match="require at least one"):
        finding(evidence_ids=())


@pytest.mark.parametrize("confidence", [-0.1, 1.1, math.inf, math.nan, True, "0.5"])
def test_confidence_must_be_finite_numeric_and_bounded(confidence: object) -> None:
    with pytest.raises(ContractError, match="confidence"):
        finding(confidence=confidence)


@pytest.mark.parametrize("digest", ["", "A" * 64, "g" * 64, "a" * 63, None])
def test_evidence_requires_lowercase_sha256(digest: object) -> None:
    with pytest.raises((ContractError, TypeError)):
        evidence(sha256=digest)


def test_evidence_rejects_empty_and_oversized_fields() -> None:
    with pytest.raises(ContractError, match="must not be empty"):
        evidence(locator="  ")
    with pytest.raises(ContractError, match="exceeds"):
        evidence(kind="x" * 4097)


def test_result_requires_explicit_nonempty_scope() -> None:
    with pytest.raises(ContractError, match="scope"):
        result(scope=())


def test_result_rejects_duplicate_evidence_ids() -> None:
    with pytest.raises(ContractError, match="duplicate evidence_id"):
        result(evidence=(evidence(), evidence()))


def test_result_rejects_duplicate_finding_ids() -> None:
    with pytest.raises(ContractError, match="duplicate finding_id"):
        result(findings=(finding(), finding()))


def test_result_rejects_unknown_evidence_reference() -> None:
    with pytest.raises(ContractError, match="unknown evidence"):
        result(findings=(finding(evidence_ids=("missing",)),))


def test_result_rejects_unknown_contract_version() -> None:
    with pytest.raises(ContractError, match="unsupported contract_version"):
        result(contract_version="nexus.intelligence/v999")


def test_from_dict_rejects_unknown_top_level_fields() -> None:
    payload = result().to_dict()
    payload["trusted"] = True
    with pytest.raises(ContractError, match="unknown fields"):
        IntelligenceResult.from_dict(payload)


def test_from_dict_rejects_unknown_finding_fields() -> None:
    payload = result().to_dict()
    payload["findings"][0]["verified_by_model"] = True
    with pytest.raises(ContractError, match="unknown fields"):
        IntelligenceResult.from_dict(payload)


def test_from_dict_rejects_non_mapping_payloads() -> None:
    with pytest.raises(ContractError, match="result must be an object"):
        IntelligenceResult.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="finding must be an object"):
        Finding.from_dict("finding")  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="evidence must be an object"):
        EvidenceReference.from_dict(None)  # type: ignore[arg-type]


def test_result_rejects_unbounded_collections() -> None:
    with pytest.raises(ContractError, match="scope exceeds"):
        result(scope=tuple(f"scope-{i}" for i in range(257)))


def test_result_rejects_non_contract_items() -> None:
    with pytest.raises(ContractError, match="findings contains an invalid item"):
        result(findings=("not-a-finding",))  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="evidence contains an invalid item"):
        result(evidence=("not-evidence",))  # type: ignore[arg-type]


def test_result_serializes_partial_status_and_limitations() -> None:
    item = result(status=ResultStatus.PARTIAL, findings=(), evidence=())
    payload = item.to_dict()
    assert payload["status"] == "partial"
    assert payload["limitations"] == ["Heuristic analysis only"]


def test_evidence_digest_is_not_mutable_through_serialized_copy() -> None:
    item = evidence()
    payload = item.to_dict()
    payload["sha256"] = "b" * 64
    assert item.sha256 == "a" * 64


def test_result_rejects_control_characters_in_identifiers() -> None:
    with pytest.raises(ContractError, match="control characters"):
        result(run_id="run-1\x00forged")


def test_contract_text_and_sequence_validation_edges() -> None:
    with pytest.raises(ContractError, match="must be a string"):
        evidence(locator=123)
    with pytest.raises(ContractError, match="control characters"):
        evidence(locator="bad\x00path")
    with pytest.raises(ContractError, match="list or tuple"):
        finding(evidence_ids="ev-1")
    with pytest.raises(ContractError, match="duplicates"):
        finding(evidence_ids=("ev-1", "ev-1"))
    with pytest.raises(ContractError, match="scope exceeds 256 items"):
        result(scope=tuple(f"scope-{i}" for i in range(257)))


def test_contract_from_dict_wraps_missing_required_fields() -> None:
    with pytest.raises(ContractError, match="invalid evidence fields"):
        EvidenceReference.from_dict({"evidence_id": "ev", "kind": "log"})
    with pytest.raises(ContractError, match="invalid finding fields"):
        Finding.from_dict({"finding_id": "f"})
    with pytest.raises(ContractError, match="invalid result fields"):
        IntelligenceResult.from_dict({"run_id": "run"})


def test_contract_rejects_invalid_enum_and_collection_item_types() -> None:
    with pytest.raises(ContractError, match="unsupported finding classification"):
        finding(severity="unrated")
    with pytest.raises(ContractError, match="unsupported result status"):
        result(status="unknown")
    with pytest.raises(ContractError, match="contains an invalid item"):
        result(findings=("not-a-finding",))
