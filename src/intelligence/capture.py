"""Safe recording adapters for externally collected behavior fixtures.

This module never executes a target or launches a process. It accepts already
collected, sanitized fixtures and stores bounded evidence through an injected
evidence sink. A future execution adapter must obtain mission authorization
and use the approved isolated runner before calling these recording functions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from .behavior import (
    BehaviorBaseline,
    BehaviorCase,
    BehaviorObservation,
    ObservationStatus,
    _required_text,
    digest_payload,
)
from .contracts import EvidenceReference

_MAX_CASES = 1000
_MAX_ARTIFACT_BYTES = 1024 * 1024
_CAPTURE_VERSION = "nexus.behavior-capture/v1"


class CaptureError(ValueError):
    """A capture fixture or evidence sink violates the recording contract."""


class EvidenceSink(Protocol):
    """Persistent evidence storage; implementations must be immutable by ID."""

    def put(
        self,
        evidence_id: str,
        payload: bytes,
        *,
        kind: str,
        collected_by: str,
    ) -> EvidenceReference:
        """Persist bytes and return a reference whose digest covers those bytes."""
        ...


@dataclass(frozen=True, slots=True)
class CapturedCase:
    """Already-collected, sanitized input/output fixture; no runner is invoked."""

    case_id: str
    input_payload: Any
    output_payload: Any
    status: ObservationStatus = ObservationStatus.PASSED

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _required_text(self.case_id, "case_id"))
        try:
            object.__setattr__(self, "status", ObservationStatus(self.status))
        except (TypeError, ValueError) as exc:
            raise CaptureError(f"unsupported capture status: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise CaptureError(f"capture fixture is not canonical JSON: {exc}") from exc
    if len(raw) > _MAX_ARTIFACT_BYTES:
        raise CaptureError("capture evidence exceeds the 1 MiB artifact limit")
    return raw


def _evidence_id(run_id: str, case_id: str) -> str:
    material = (run_id + "\0" + case_id).encode("utf-8")
    return "behavior-" + hashlib.sha256(material).hexdigest()[:32]


def _store_case(
    case: CapturedCase,
    *,
    run_id: str,
    target: str,
    revision: str,
    collected_by: str,
    sink: EvidenceSink,
) -> tuple[str, str, str, EvidenceReference]:
    input_hash = digest_payload(case.input_payload)
    output_hash = digest_payload(case.output_payload)
    artifact = {
        "contract": _CAPTURE_VERSION,
        "run_id": run_id,
        "target": target,
        "revision": revision,
        "case_id": case.case_id,
        "input": case.input_payload,
        "output": case.output_payload,
        "input_sha256": input_hash,
        "output_sha256": output_hash,
        "status": case.status.value,
    }
    payload = _canonical_bytes(artifact)
    evidence_id = _evidence_id(run_id, case.case_id)
    try:
        reference = sink.put(
            evidence_id, payload, kind="behavior-capture", collected_by=collected_by
        )
    except Exception as exc:
        raise CaptureError(f"evidence sink rejected case {case.case_id}: {exc}") from exc
    if not isinstance(reference, EvidenceReference):
        raise CaptureError("evidence sink must return an EvidenceReference")
    if (
        reference.evidence_id != evidence_id
        or reference.kind != "behavior-capture"
        or reference.collected_by != collected_by
        or reference.sha256 != hashlib.sha256(payload).hexdigest()
    ):
        raise CaptureError("evidence sink returned a mismatched ID, kind, collector, or digest")
    return input_hash, output_hash, evidence_id, reference


def capture_baseline(
    *,
    target: str,
    revision: str,
    run_id: str,
    cases: tuple[CapturedCase, ...] | list[CapturedCase],
    collected_by: str,
    sink: EvidenceSink,
) -> BehaviorBaseline:
    """Record successful, pre-collected fixtures as a behavior baseline.

    Input/output fixtures must be sanitized test data. This function does not
    run the commands or functions that produced them.
    """
    target = _required_text(target, "target")
    revision = _required_text(revision, "revision")
    run_id = _required_text(run_id, "run_id")
    collected_by = _required_text(collected_by, "collected_by")
    if not isinstance(cases, (tuple, list)) or not 1 <= len(cases) <= _MAX_CASES:
        raise CaptureError("baseline capture requires between 1 and 1000 cases")
    if any(not isinstance(case, CapturedCase) for case in cases):
        raise CaptureError("capture contains an invalid case")
    if any(case.status is not ObservationStatus.PASSED for case in cases):
        raise CaptureError("baseline cases must all have passed")
    if len({case.case_id for case in cases}) != len(cases):
        raise CaptureError("capture contains duplicate case IDs")
    if not callable(getattr(sink, "put", None)):
        raise CaptureError("a persistent evidence sink is required")

    recorded: list[BehaviorCase] = []
    references: list[EvidenceReference] = []
    for case in cases:
        input_hash, output_hash, evidence_id, reference = _store_case(
            case, run_id=run_id, target=target, revision=revision,
            collected_by=collected_by, sink=sink,
        )
        recorded.append(BehaviorCase(case.case_id, input_hash, output_hash, evidence_id))
        references.append(reference)
    return BehaviorBaseline(target, revision, tuple(recorded), tuple(references))


def capture_observations(
    *,
    target: str,
    revision: str,
    run_id: str,
    cases: tuple[CapturedCase, ...] | list[CapturedCase],
    collected_by: str,
    sink: EvidenceSink,
) -> tuple[tuple[BehaviorObservation, ...], tuple[EvidenceReference, ...]]:
    """Record candidate observations from an already-authorized external harness."""
    target = _required_text(target, "target")
    revision = _required_text(revision, "revision")
    run_id = _required_text(run_id, "run_id")
    collected_by = _required_text(collected_by, "collected_by")
    if not isinstance(cases, (tuple, list)) or len(cases) > _MAX_CASES:
        raise CaptureError("observation capture accepts at most 1000 cases")
    if any(not isinstance(case, CapturedCase) for case in cases):
        raise CaptureError("capture contains an invalid case")
    if len({case.case_id for case in cases}) != len(cases):
        raise CaptureError("capture contains duplicate case IDs")
    if not callable(getattr(sink, "put", None)):
        raise CaptureError("a persistent evidence sink is required")

    observations: list[BehaviorObservation] = []
    references: list[EvidenceReference] = []
    for case in cases:
        input_hash, output_hash, evidence_id, reference = _store_case(
            case, run_id=run_id, target=target, revision=revision,
            collected_by=collected_by, sink=sink,
        )
        observations.append(
            BehaviorObservation(
                case.case_id, input_hash, output_hash, case.status, evidence_id
            )
        )
        references.append(reference)
    return tuple(observations), tuple(references)


__all__ = [
    "CaptureError", "CapturedCase", "EvidenceSink",
    "capture_baseline", "capture_observations",
]
