"""Targeted edge-case coverage for intelligence evidence contracts."""
from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from src.intelligence.behavior import (
    BehaviorBaseline, BehaviorCase, BehaviorComparison, BehaviorContractError,
    BehaviorObservation, BehaviorVerdict, ObservationStatus, compare_behavior,
    digest_payload,
)
from src.intelligence.capture import (
    CaptureError, CapturedCase, _canonical_bytes, capture_baseline,
    capture_observations, sanitize_payload,
)
from src.intelligence.contracts import EvidenceReference
from src.intelligence.mission import BehaviorCaseSpec, MissionBehaviorError
from src.intelligence.replay import BehaviorReplayError, ReplayCommandCase


def test_sanitizer_handles_nested_values_and_all_supported_secret_forms() -> None:
    token = "ghp_" + "a" * 30
    github_pat = "github_pat_" + "b" * 30
    payload = {
        "nested": [{"safe": "ok", "refresh_token": "refresh-value"}],
        "text": (
            "Bearer abc.def.ghi api_key=key-value token:plain-token "
            + token + " " + github_pat + " AKIA1234567890ABCDEF"
        ),
        "private": (
            "-----BEGIN " + "PRIVATE KEY" + "-----"
            + "\nsecret-material\n"
            + "-----END " + "PRIVATE KEY" + "-----"
        ),
    }
    clean = sanitize_payload(payload)
    assert clean["nested"][0]["safe"] == "ok"
    assert clean["nested"][0]["refresh_token"] == "[REDACTED]"
    serialized = repr(clean)
    for secret in (
        "refresh-value", "abc.def.ghi", "key-value", "plain-token",
        token, github_pat, "AKIA1234567890ABCDEF", "secret-material",
    ):
        assert secret not in serialized


def test_sanitizer_redacts_non_string_secret_field_names() -> None:
    assert sanitize_payload({"client_secret": {"nested": "value"}}) == {
        "client_secret": "[REDACTED]"
    }


def test_capture_canonicalization_rejects_nan_and_oversized_payloads() -> None:
    with pytest.raises(CaptureError, match="canonical JSON"):
        _canonical_bytes({"number": float("nan")})
    with pytest.raises(CaptureError, match="1 MiB"):
        _canonical_bytes("x" * (1024 * 1024))


def test_behavior_digest_rejects_noncanonical_and_oversized_payloads() -> None:
    with pytest.raises(BehaviorContractError, match="canonical JSON"):
        digest_payload({"number": float("inf")})
    with pytest.raises(BehaviorContractError, match="1 MiB"):
        digest_payload("x" * (1024 * 1024))


@pytest.mark.parametrize(
    "case_id,argv,timeout,payload",
    [
        ("", ("cat", "{behavior_input}"), 10, {}),
        ("valid", (), 10, {}),
        ("valid", ("cat", "\x00", "{behavior_input}"), 10, {}),
        ("valid", ("cat", "{behavior_input}"), True, {}),
        ("valid", ("cat", "{behavior_input}"), 301, {}),
        ("valid", ("cat", "{behavior_input}"), 10, object()),
    ],
)
def test_behavior_case_spec_rejects_invalid_contracts(
    case_id: str, argv: tuple[str, ...], timeout: int, payload: object
) -> None:
    with pytest.raises(MissionBehaviorError):
        BehaviorCaseSpec(case_id, argv, payload, timeout)


def test_replay_case_rejects_bad_workspace_and_payload(tmp_path: Path) -> None:
    with pytest.raises(BehaviorReplayError, match="existing non-symlink"):
        ReplayCommandCase(
            "case", ("cat",), tmp_path / "missing", {},
        )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(BehaviorReplayError, match="filesystem path"):
        ReplayCommandCase("case", ("cat",), None, {})  # type: ignore[arg-type]
    with pytest.raises(BehaviorReplayError, match="timeout"):
        ReplayCommandCase("case", ("cat",), workspace, {}, True)
    with pytest.raises(BehaviorReplayError, match="input fixture"):
        ReplayCommandCase("case", ("cat",), workspace, object())


class _CoverageSink:
    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
        self.items: dict[str, bytes] = {}

    def put(self, evidence_id, payload, *, kind, collected_by):
        if self.mode == "raise":
            raise RuntimeError("sink token=do-not-leak")
        self.items[evidence_id] = payload
        reference = EvidenceReference(
            evidence_id, kind, f"memory://{evidence_id}",
            hashlib.sha256(payload).hexdigest(), collected_by,
        )
        if self.mode == "wrong-id":
            return EvidenceReference(
                "wrong-id", kind, reference.locator, reference.sha256, collected_by
            )
        if self.mode == "wrong-type":
            return {"evidence_id": evidence_id}
        return reference


def _baseline_for_comparison(status=ObservationStatus.PASSED):
    import hashlib
    input_hash = digest_payload({"request": "/health"})
    output_hash = digest_payload({"status": 200})
    evidence = EvidenceReference(
        "baseline-ev", "behavior-capture", "memory://baseline-ev",
        hashlib.sha256(b"baseline").hexdigest(), "baseline",
    )
    baseline = BehaviorBaseline(
        "service", "rev-1",
        (BehaviorCase("health", input_hash, output_hash, "baseline-ev"),),
        (evidence,),
    )
    observed_evidence = EvidenceReference(
        "candidate-ev", "behavior-capture", "memory://candidate-ev",
        hashlib.sha256(b"candidate").hexdigest(), "candidate",
    )
    observation = BehaviorObservation(
        "health", input_hash, output_hash, status, "candidate-ev"
    )
    return baseline, observation, observed_evidence


def test_capture_rejects_invalid_baseline_inputs_and_sink_contracts() -> None:
    sink = _CoverageSink()
    common = dict(
        target="service", revision="rev-1", run_id="run-1",
        collected_by="test", sink=sink,
    )
    with pytest.raises(CaptureError, match="between 1 and 1000"):
        capture_baseline(cases=[], **common)
    with pytest.raises(CaptureError, match="invalid case"):
        capture_baseline(cases=[object()], **common)
    with pytest.raises(CaptureError, match="all have passed"):
        capture_baseline(cases=[CapturedCase("bad", {}, {}, ObservationStatus.FAILED)], **common)
    duplicate = [CapturedCase("same", {}, {}), CapturedCase("same", {}, {})]
    with pytest.raises(CaptureError, match="duplicate"):
        capture_baseline(cases=duplicate, **common)
    with pytest.raises(CaptureError, match="persistent evidence sink"):
        capture_baseline(cases=[CapturedCase("ok", {}, {})], **{**common, "sink": object()})
    for mode, message in (("raise", "sink rejected"), ("wrong-id", "mismatched"), ("wrong-type", "EvidenceReference")):
        with pytest.raises(CaptureError, match=message):
            capture_baseline(
                cases=[CapturedCase("ok", {}, {})],
                **{**common, "sink": _CoverageSink(mode)},
            )


def test_capture_observations_accepts_empty_and_rejects_invalid_contracts() -> None:
    sink = _CoverageSink()
    common = dict(
        target="service", revision="rev-2", run_id="run-2",
        collected_by="test", sink=sink,
    )
    assert capture_observations(cases=[], **common) == ((), ())
    with pytest.raises(CaptureError, match="invalid case"):
        capture_observations(cases=[object()], **common)
    with pytest.raises(CaptureError, match="duplicate"):
        capture_observations(
            cases=[CapturedCase("same", {}, {}), CapturedCase("same", {}, {})],
            **common,
        )
    with pytest.raises(CaptureError, match="persistent evidence sink"):
        capture_observations(cases=[CapturedCase("ok", {}, {})], **{**common, "sink": object()})


def test_behavior_baseline_and_observation_deserialization_reject_bad_shapes() -> None:
    with pytest.raises(BehaviorContractError, match="exactly"):
        BehaviorBaseline.from_dict({"target": "x"})
    with pytest.raises(BehaviorContractError, match="arrays"):
        BehaviorBaseline.from_dict({
            "target": "x", "revision": "r", "cases": {}, "evidence": [],
        })
    with pytest.raises(BehaviorContractError, match="unknown or missing"):
        BehaviorBaseline.from_dict({
            "target": "x", "revision": "r",
            "cases": [{"case_id": "x"}], "evidence": [],
        })
    with pytest.raises(BehaviorContractError, match="unknown or missing"):
        BehaviorObservation.from_dict({"case_id": "x"})
    with pytest.raises(BehaviorContractError, match="unsupported observation status"):
        BehaviorObservation("x", "a" * 64, "b" * 64, "unknown", "ev")


@pytest.mark.parametrize(
    "mutator,expected",
    [
        (lambda b, o, e: (None, o, e), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, object(), e), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, [object()], e), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, [o, o], e), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, [o], []), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, [o], [e, e]), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, [o], [b.evidence[0]]), BehaviorVerdict.INVALID),
        (lambda b, o, e: (b, [o], [EvidenceReference("other", e.kind, e.locator, e.sha256, e.collected_by)]), BehaviorVerdict.INVALID),
    ],
)
def test_behavior_comparison_rejects_invalid_evidence_mappings(mutator, expected) -> None:
    baseline, observation, evidence = _baseline_for_comparison()
    actual_baseline, observations, references = mutator(baseline, observation, evidence)
    result = compare_behavior(
        actual_baseline, observations, observation_evidence=references,
        verify_evidence=lambda _: True,
    )
    assert result.verdict is expected


def test_behavior_comparison_handles_verification_and_verdict_branches() -> None:
    baseline, observation, evidence = _baseline_for_comparison()
    invalid = compare_behavior(
        baseline, [observation], observation_evidence=[evidence],
        verify_evidence=lambda _: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert invalid.verdict is BehaviorVerdict.INVALID
    assert compare_behavior(
        baseline, [observation], observation_evidence=[evidence],
        verify_evidence=lambda _: True,
    ).verdict is BehaviorVerdict.EQUIVALENT
    assert compare_behavior(
        baseline, [], observation_evidence=[], verify_evidence=lambda _: True,
    ).verdict is BehaviorVerdict.INCOMPLETE
    unexpected = BehaviorObservation(
        "other", observation.input_sha256, observation.output_sha256,
        ObservationStatus.PASSED, "candidate-ev",
    )
    assert compare_behavior(
        baseline, [unexpected], observation_evidence=[evidence],
        verify_evidence=lambda _: True,
    ).verdict is BehaviorVerdict.INVALID
    changed_input = BehaviorObservation(
        "health", "c" * 64, observation.output_sha256,
        ObservationStatus.PASSED, "candidate-ev",
    )
    assert compare_behavior(
        baseline, [changed_input], observation_evidence=[evidence],
        verify_evidence=lambda _: True,
    ).verdict is BehaviorVerdict.INVALID
    for status, output_hash, expected in (
        (ObservationStatus.FAILED, observation.output_sha256, BehaviorVerdict.REGRESSION),
        (ObservationStatus.PASSED, "d" * 64, BehaviorVerdict.REGRESSION),
        (ObservationStatus.NOT_RUN, observation.output_sha256, BehaviorVerdict.INCOMPLETE),
    ):
        candidate = BehaviorObservation(
            "health", observation.input_sha256, output_hash, status, "candidate-ev"
        )
        assert compare_behavior(
            baseline, [candidate], observation_evidence=[evidence],
            verify_evidence=lambda _: True,
        ).verdict is expected
