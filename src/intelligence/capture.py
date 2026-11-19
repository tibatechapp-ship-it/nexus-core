"""Safe recording adapters for externally collected behavior fixtures.

This module never executes a target or launches a process. It accepts already
collected fixtures, redacts common credential forms before hashing or storage,
and stores bounded evidence through an injected immutable evidence sink.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
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
_REDACTED = "[REDACTED]"
_SECRET_KEY_SUFFIXES = (
    "password", "passwd", "secret", "token", "apikey", "accesskey",
    "privatekey", "clientsecret", "authorization", "cookie", "credential",
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/-]+=*"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"client[_-]?secret|password|passwd|secret)\s*([=:])\s*"
        r"(['\"]?)[^\s,'\";}]+"
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)


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
    """Already-collected input/output fixture; common credentials are redacted."""

    case_id: str
    input_payload: Any
    output_payload: Any
    status: ObservationStatus = ObservationStatus.PASSED

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "case_id", _required_text(self.case_id, "case_id"))
        except ValueError as exc:
            raise CaptureError(str(exc)) from exc
        try:
            object.__setattr__(self, "status", ObservationStatus(self.status))
        except (TypeError, ValueError) as exc:
            raise CaptureError(f"unsupported capture status: {exc}") from exc


def _is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    compact = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(compact.endswith(suffix) for suffix in _SECRET_KEY_SUFFIXES)


def _redact_string(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            if pattern.pattern.startswith("(?i)\\b(Bearer"):
                result = pattern.sub(lambda match: match.group(1) + _REDACTED, result)
            elif "api[_-]?" in pattern.pattern:
                result = pattern.sub(
                    lambda match: match.group(1) + match.group(2) + _REDACTED,
                    result,
                )
            else:
                result = pattern.sub(_REDACTED, result)
        else:
            result = pattern.sub(_REDACTED, result)
    return result


def _sanitize_payload(value: Any, *, field_name: Any = None) -> Any:
    """Return a JSON-shaped copy with credential-bearing fields and strings redacted."""
    if _is_secret_key(field_name):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            key: _sanitize_payload(item, field_name=key)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


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
    sanitized_input = _sanitize_payload(case.input_payload)
    sanitized_output = _sanitize_payload(case.output_payload)
    try:
        input_hash = digest_payload(sanitized_input)
        output_hash = digest_payload(sanitized_output)
    except ValueError as exc:
        raise CaptureError(f"case {case.case_id} contains an invalid or oversized payload: {exc}") from exc
    artifact = {
        "contract": _CAPTURE_VERSION,
        "run_id": run_id,
        "target": target,
        "revision": revision,
        "case_id": case.case_id,
        "input": sanitized_input,
        "output": sanitized_output,
        "input_sha256": input_hash,
        "output_sha256": output_hash,
        "status": case.status.value,
        "redaction": "nexus.secret-redaction/v1",
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
    """Record successful pre-collected fixtures after credential redaction.

    Redaction is defense in depth, not a guarantee that arbitrary personal or
    confidential data is safe. Callers must still provide sanitized test data.
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
    """Record candidate observations after credential redaction."""
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
