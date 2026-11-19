"""Tests for evidence-backed behavior baseline comparison."""

from __future__ import annotations

import pytest

from src.intelligence import EvidenceReference
from src.intelligence.behavior import (
    BehaviorBaseline, BehaviorCase, BehaviorContractError, BehaviorObservation,
    BehaviorGateVerdict, BehaviorVerdict, ObservationStatus, compare_behavior,
    digest_payload, evaluate_behavior_gate,
)
from src.intelligence.gate import AssuranceDecision, AssuranceVerdict


_INPUT = "1" * 64
_OUTPUT = "2" * 64
_EVIDENCE = EvidenceReference("base-ev", "baseline", "baseline.json", "a" * 64, "test")
_OBS_EVIDENCE = EvidenceReference("run-ev", "observation", "run.json", "b" * 64, "test")


def _baseline() -> BehaviorBaseline:
    return BehaviorBaseline(
        target="repo:sample", revision="abc123",
        cases=(BehaviorCase("case-1", _INPUT, _OUTPUT, "base-ev"),),
        evidence=(_EVIDENCE,),
    )


def _observation(
    *, input_hash: str = _INPUT, output_hash: str = _OUTPUT,
    status: ObservationStatus = ObservationStatus.PASSED,
) -> BehaviorObservation:
    return BehaviorObservation("case-1", input_hash, output_hash, status, "run-ev")


def _compare(observations: tuple[BehaviorObservation, ...], verifier=lambda _: True):
    references = (_OBS_EVIDENCE,) if observations else ()
    return compare_behavior(
        _baseline(), observations, observation_evidence=references,
        verify_evidence=verifier,
    )


def test_digest_payload_is_stable_for_mapping_order() -> None:
    assert digest_payload({"b": 2, "a": 1}) == digest_payload({"a": 1, "b": 2})


def test_digest_payload_rejects_non_json_and_nan() -> None:
    with pytest.raises(BehaviorContractError):
        digest_payload({"bad": float("nan")})
    with pytest.raises(BehaviorContractError):
        digest_payload(object())


def test_baseline_requires_cases_and_evidence() -> None:
    with pytest.raises(BehaviorContractError):
        BehaviorBaseline("repo", "rev", (), (_EVIDENCE,))
    with pytest.raises(BehaviorContractError):
        BehaviorBaseline("repo", "rev", (BehaviorCase("c", _INPUT, _OUTPUT, "missing"),), (_EVIDENCE,))


def test_case_rejects_invalid_digest() -> None:
    with pytest.raises(BehaviorContractError):
        BehaviorCase("c", "not-a-digest", _OUTPUT, "ev")


def test_observation_rejects_unknown_status() -> None:
    with pytest.raises(BehaviorContractError):
        BehaviorObservation("c", _INPUT, _OUTPUT, "unknown", "ev")


def test_matching_observations_are_equivalent() -> None:
    result = _compare((_observation(),))
    assert result.verdict is BehaviorVerdict.EQUIVALENT
    assert result.equivalent
    assert result.matched_case_ids == ("case-1",)
    assert set(result.verified_evidence_ids) == {"base-ev", "run-ev"}


def test_missing_observation_is_incomplete() -> None:
    result = _compare(())
    assert result.verdict is BehaviorVerdict.INCOMPLETE
    assert result.missing_case_ids == ("case-1",)


def test_not_run_observation_is_incomplete() -> None:
    result = _compare((_observation(status=ObservationStatus.NOT_RUN),))
    assert result.verdict is BehaviorVerdict.INCOMPLETE


def test_failed_observation_is_regression() -> None:
    result = _compare((_observation(status=ObservationStatus.FAILED),))
    assert result.verdict is BehaviorVerdict.REGRESSION


def test_changed_output_is_regression() -> None:
    result = _compare((_observation(output_hash="3" * 64),))
    assert result.verdict is BehaviorVerdict.REGRESSION
    assert result.changed_case_ids == ("case-1",)


def test_changed_input_is_invalid_comparison() -> None:
    result = _compare((_observation(input_hash="4" * 64),))
    assert result.verdict is BehaviorVerdict.INVALID


def test_unexpected_case_is_invalid() -> None:
    extra = BehaviorObservation("extra", _INPUT, _OUTPUT, ObservationStatus.PASSED, "run-ev")
    result = _compare((_observation(), extra))
    assert result.verdict is BehaviorVerdict.INVALID
    assert result.unexpected_case_ids == ("extra",)


def test_duplicate_observations_are_invalid() -> None:
    result = _compare((_observation(), _observation()))
    assert result.verdict is BehaviorVerdict.INVALID


def test_unverified_evidence_fails_closed() -> None:
    result = _compare((_observation(),), verifier=lambda _: False)
    assert result.verdict is BehaviorVerdict.INVALID


def test_verifier_exception_fails_closed() -> None:
    def broken(_: EvidenceReference) -> bool:
        raise RuntimeError("storage unavailable")
    result = _compare((_observation(),), verifier=broken)
    assert result.verdict is BehaviorVerdict.INVALID


def test_invalid_baseline_and_missing_verifier_fail_closed() -> None:
    assert compare_behavior(
        None, (), observation_evidence=(), verify_evidence=lambda _: True
    ).verdict is BehaviorVerdict.INVALID
    assert compare_behavior(
        _baseline(), (), observation_evidence=(), verify_evidence=None
    ).verdict is BehaviorVerdict.INVALID


def test_observation_must_reference_known_evidence() -> None:
    bad = BehaviorObservation("case-1", _INPUT, _OUTPUT, ObservationStatus.PASSED, "unknown")
    assert _compare((bad,)).verdict is BehaviorVerdict.INVALID


def test_decision_serialization_is_stable() -> None:
    result = _compare((_observation(),))
    assert result.to_dict()["verdict"] == "equivalent"
    assert result.to_dict()["equivalent"] is True



def test_baseline_round_trip_serialization() -> None:
    baseline = _baseline()
    assert BehaviorBaseline.from_dict(baseline.to_dict()) == baseline


def test_baseline_rejects_unknown_serialized_fields() -> None:
    payload = _baseline().to_dict()
    payload["untrusted"] = True
    with pytest.raises(BehaviorContractError):
        BehaviorBaseline.from_dict(payload)


def test_observation_round_trip_serialization() -> None:
    observation = _observation()
    assert BehaviorObservation.from_dict(observation.to_dict()) == observation


def test_observation_rejects_unknown_serialized_fields() -> None:
    payload = _observation().to_dict()
    payload["extra"] = "ignored?"
    with pytest.raises(BehaviorContractError):
        BehaviorObservation.from_dict(payload)


def test_baseline_and_candidate_evidence_ids_cannot_collide() -> None:
    colliding = EvidenceReference("base-ev", "observation", "run.json", "b" * 64, "test")
    result = compare_behavior(
        _baseline(), (_observation(),), observation_evidence=(colliding,),
        verify_evidence=lambda _: True,
    )
    assert result.verdict is BehaviorVerdict.INVALID


def test_observation_evidence_count_is_bounded() -> None:
    refs = tuple(
        EvidenceReference(f"run-{i}", "observation", f"run-{i}.json", "b" * 64, "test")
        for i in range(5001)
    )
    result = compare_behavior(
        _baseline(), (_observation(),), observation_evidence=refs,
        verify_evidence=lambda _: True,
    )
    assert result.verdict is BehaviorVerdict.INVALID



def test_combined_gate_assures_only_when_both_gates_pass() -> None:
    assurance = AssuranceDecision(AssuranceVerdict.ASSURED, ("evidence verified",), ("base-ev", "run-ev"))
    behavior = _compare((_observation(),))
    decision = evaluate_behavior_gate(assurance, behavior)
    assert decision.verdict is BehaviorGateVerdict.ASSURED
    assert decision.accepted


def test_combined_gate_rejects_behavior_regression() -> None:
    assurance = AssuranceDecision(AssuranceVerdict.ASSURED, ("evidence verified",), ("base-ev", "run-ev"))
    behavior = _compare((_observation(output_hash="3" * 64),))
    assert evaluate_behavior_gate(assurance, behavior).verdict is BehaviorGateVerdict.REJECTED


def test_combined_gate_requires_human_for_incomplete_behavior() -> None:
    assurance = AssuranceDecision(AssuranceVerdict.ASSURED, ("evidence verified",), ("base-ev",))
    decision = evaluate_behavior_gate(assurance, _compare(()))
    assert decision.verdict is BehaviorGateVerdict.NEEDS_HUMAN


def test_combined_gate_rejects_unassured_evidence() -> None:
    assurance = AssuranceDecision(AssuranceVerdict.REJECTED, ("digest mismatch",), ())
    decision = evaluate_behavior_gate(assurance, _compare((_observation(),)))
    assert decision.verdict is BehaviorGateVerdict.REJECTED


def test_combined_gate_requires_human_for_partial_assurance() -> None:
    assurance = AssuranceDecision(AssuranceVerdict.NEEDS_HUMAN, ("partial result",), ("base-ev",))
    decision = evaluate_behavior_gate(assurance, _compare((_observation(),)))
    assert decision.verdict is BehaviorGateVerdict.NEEDS_HUMAN


def test_combined_gate_rejects_invalid_inputs() -> None:
    decision = evaluate_behavior_gate(None, None)
    assert decision.verdict is BehaviorGateVerdict.REJECTED



def test_baseline_rejects_reused_or_orphaned_evidence_references() -> None:
    with pytest.raises(BehaviorContractError, match="distinct evidence"):
        BehaviorBaseline(
            "repo", "rev",
            (
                BehaviorCase("one", _INPUT, _OUTPUT, "base-ev"),
                BehaviorCase("two", _INPUT, _OUTPUT, "base-ev"),
            ),
            (_EVIDENCE,),
        )
    orphan = EvidenceReference("orphan", "baseline", "orphan.json", "c" * 64, "test")
    with pytest.raises(BehaviorContractError, match="one-to-one"):
        BehaviorBaseline(
            "repo", "rev",
            (BehaviorCase("one", _INPUT, _OUTPUT, "base-ev"),),
            (_EVIDENCE, orphan),
        )


def test_candidate_evidence_must_map_one_to_one_to_observations() -> None:
    orphan = EvidenceReference("orphan", "observation", "orphan.json", "c" * 64, "test")
    result = compare_behavior(
        _baseline(), (_observation(),), observation_evidence=(_OBS_EVIDENCE, orphan),
        verify_evidence=lambda _: True,
    )
    assert result.verdict is BehaviorVerdict.INVALID


def test_duplicate_candidate_evidence_reference_is_invalid() -> None:
    duplicate = BehaviorObservation(
        "other-case", _INPUT, _OUTPUT, ObservationStatus.PASSED, "run-ev"
    )
    result = compare_behavior(
        _baseline(), (_observation(), duplicate),
        observation_evidence=(_OBS_EVIDENCE,), verify_evidence=lambda _: True,
    )
    assert result.verdict is BehaviorVerdict.INVALID
