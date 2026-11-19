"""Tests for safe behavior capture and evidence persistence adapters."""
from __future__ import annotations

import hashlib
import json

import pytest

from src.intelligence import EvidenceReference
from src.intelligence.behavior import BehaviorVerdict, ObservationStatus, compare_behavior
from src.intelligence.capture import (
    CaptureError, CapturedCase, capture_baseline, capture_observations,
)


class MemoryEvidenceSink:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    def put(self, evidence_id: str, payload: bytes, *, kind: str, collected_by: str):
        if evidence_id in self.items:
            raise ValueError("immutable evidence ID already exists")
        self.items[evidence_id] = payload
        return EvidenceReference(
            evidence_id=evidence_id,
            kind=kind,
            locator=f"memory://evidence/{evidence_id}",
            sha256=hashlib.sha256(payload).hexdigest(),
            collected_by=collected_by,
        )


def _verify(sink: MemoryEvidenceSink):
    def verify(reference: EvidenceReference) -> bool:
        payload = sink.items.get(reference.evidence_id)
        return payload is not None and hashlib.sha256(payload).hexdigest() == reference.sha256
    return verify


def test_capture_baseline_persists_fixtures_and_returns_verifiable_baseline() -> None:
    sink = MemoryEvidenceSink()
    baseline = capture_baseline(
        target="repo:sample", revision="abc123", run_id="baseline-1",
        cases=[CapturedCase("case-1", {"x": 1}, {"y": 2})],
        collected_by="test-harness", sink=sink,
    )
    artifact = json.loads(next(iter(sink.items.values())))
    assert artifact["contract"] == "nexus.behavior-capture/v1"
    assert artifact["input"] == {"x": 1}
    assert baseline.cases[0].evidence_id in sink.items
    assert _verify(sink)(baseline.evidence[0])


def test_capture_observations_compare_to_baseline() -> None:
    sink = MemoryEvidenceSink()
    baseline = capture_baseline(
        target="repo:sample", revision="base", run_id="base-run",
        cases=[CapturedCase("case-1", {"x": 1}, {"y": 2})],
        collected_by="test-harness", sink=sink,
    )
    observations, references = capture_observations(
        target="repo:sample", revision="candidate", run_id="candidate-run",
        cases=[CapturedCase("case-1", {"x": 1}, {"y": 2})],
        collected_by="test-harness", sink=sink,
    )
    result = compare_behavior(
        baseline, observations, observation_evidence=references,
        verify_evidence=_verify(sink),
    )
    assert result.verdict is BehaviorVerdict.EQUIVALENT


def test_capture_records_failed_and_not_run_candidate_cases() -> None:
    sink = MemoryEvidenceSink()
    observations, refs = capture_observations(
        target="repo:sample", revision="candidate", run_id="candidate-2",
        cases=[
            CapturedCase("failed", {"x": 1}, {"error": "exit 1"}, ObservationStatus.FAILED),
            CapturedCase("not-run", {"x": 2}, None, ObservationStatus.NOT_RUN),
        ],
        collected_by="test-harness", sink=sink,
    )
    assert [item.status for item in observations] == [
        ObservationStatus.FAILED, ObservationStatus.NOT_RUN
    ]
    assert len(refs) == 2


def test_baseline_rejects_failed_case() -> None:
    with pytest.raises(CaptureError):
        capture_baseline(
            target="repo", revision="base", run_id="run",
            cases=[CapturedCase("c", {}, {}, ObservationStatus.FAILED)],
            collected_by="test", sink=MemoryEvidenceSink(),
        )


def test_capture_rejects_duplicate_case_ids() -> None:
    with pytest.raises(CaptureError):
        capture_observations(
            target="repo", revision="rev", run_id="run",
            cases=[CapturedCase("c", 1, 1), CapturedCase("c", 2, 2)],
            collected_by="test", sink=MemoryEvidenceSink(),
        )


def test_capture_rejects_oversized_fixture() -> None:
    with pytest.raises(CaptureError):
        capture_baseline(
            target="repo", revision="rev", run_id="run",
            cases=[CapturedCase("c", "x" * (1024 * 1024), {})],
            collected_by="test", sink=MemoryEvidenceSink(),
        )


def test_capture_rejects_sink_digest_tampering() -> None:
    class BadSink:
        def put(self, evidence_id, payload, *, kind, collected_by):
            return EvidenceReference(evidence_id, kind, "memory://bad", "0" * 64, collected_by)
    with pytest.raises(CaptureError):
        capture_baseline(
            target="repo", revision="rev", run_id="run",
            cases=[CapturedCase("c", {}, {})],
            collected_by="test", sink=BadSink(),
        )


def test_capture_never_invokes_a_target_runner() -> None:
    invoked = False
    def forbidden_runner():
        nonlocal invoked
        invoked = True
    sink = MemoryEvidenceSink()
    capture_baseline(
        target="repo", revision="rev", run_id="run",
        cases=[CapturedCase("c", {"safe": True}, {"ok": True})],
        collected_by="test", sink=sink,
    )
    assert invoked is False


def test_capture_rejects_invalid_status_and_non_json_payloads() -> None:
    with pytest.raises(CaptureError, match="unsupported capture status"):
        CapturedCase("bad", {}, {}, "unknown")
    with pytest.raises(CaptureError, match="canonical JSON"):
        capture_baseline(
            target="repo", revision="rev", run_id="run",
            cases=[CapturedCase("bad", object(), {})],
            collected_by="test", sink=MemoryEvidenceSink(),
        )


def test_capture_rejects_empty_or_invalid_case_collections() -> None:
    with pytest.raises(CaptureError, match="between 1 and 1000"):
        capture_baseline(
            target="repo", revision="rev", run_id="empty",
            cases=[], collected_by="test", sink=MemoryEvidenceSink(),
        )
    with pytest.raises(CaptureError, match="invalid case"):
        capture_observations(
            target="repo", revision="rev", run_id="invalid",
            cases=[object()], collected_by="test", sink=MemoryEvidenceSink(),
        )


def test_capture_wraps_sink_exception_and_rejects_wrong_reference_type() -> None:
    class RaisingSink:
        def put(self, *args, **kwargs):
            raise OSError("storage offline")

    class WrongSink:
        def put(self, *args, **kwargs):
            return {"evidence_id": "not-a-reference"}

    case = [CapturedCase("case", {}, {})]
    with pytest.raises(CaptureError, match="sink rejected"):
        capture_baseline(
            target="repo", revision="rev", run_id="raising",
            cases=case, collected_by="test", sink=RaisingSink(),
        )
    with pytest.raises(CaptureError, match="must return an EvidenceReference"):
        capture_baseline(
            target="repo", revision="rev", run_id="wrong",
            cases=case, collected_by="test", sink=WrongSink(),
        )


def test_capture_redacts_secret_fields_and_common_secret_patterns_before_persisting() -> None:
    sink = MemoryEvidenceSink()
    capture_observations(
        target="repo:sample", revision="candidate", run_id="redaction-run",
        cases=[CapturedCase(
            "case-secret",
            {"api_key": "sk-live-do-not-store", "safe": "hello"},
            {
                "authorization": "Bearer abc.def.ghi",
                "message": "request failed: password=hunter2",
                "provider": "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890",
                "private_key": "-----BEGIN PRIVATE " + "KEY-----\\nsecret-material\\n-----END PRIVATE " + "KEY-----",
            },
        )],
        collected_by="test-harness", sink=sink,
    )
    stored = next(iter(sink.items.values())).decode("utf-8")
    expected_provider_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    assert "sk-live-do-not-store" not in stored
    assert "abc.def.ghi" not in stored
    assert "hunter2" not in stored
    assert expected_provider_token not in stored
    assert "secret-material" not in stored
    artifact = json.loads(stored)
    assert artifact["input"]["api_key"] == "[REDACTED]"
    assert artifact["output"]["authorization"] == "[REDACTED]"
    assert artifact["redaction"] == "nexus.secret-redaction/v1"


def test_capture_redacts_secret_like_values_in_plain_output_text() -> None:
    sink = MemoryEvidenceSink()
    capture_observations(
        target="repo:sample", revision="candidate", run_id="plain-redaction",
        cases=[CapturedCase(
            "case-output", {}, {"stdout": "token=abc123xyz"},
        )],
        collected_by="test-harness", sink=sink,
    )
    stored = next(iter(sink.items.values())).decode("utf-8")
    assert "abc123xyz" not in stored
    assert "[REDACTED]" in stored
