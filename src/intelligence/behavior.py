"""Evidence-backed behavioral baseline comparison.

This module compares observations supplied by an already-authorized harness.
It never launches target code, imports a target repository, or invokes a runner.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from .contracts import EvidenceReference
from .gate import AssuranceDecision, AssuranceVerdict

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_CASES = 1000
_MAX_EVIDENCE = 5000
_MAX_PAYLOAD_BYTES = 1024 * 1024


class BehaviorContractError(ValueError):
    """A baseline or observation violates the behavior contract."""


class ObservationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class BehaviorVerdict(StrEnum):
    EQUIVALENT = "equivalent"
    REGRESSION = "regression"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BehaviorContractError(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > 4096 or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise BehaviorContractError(f"{field} is invalid or too long")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise BehaviorContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def digest_payload(value: Any) -> str:
    """Hash canonical JSON; callers must normalize nondeterministic fields first."""
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise BehaviorContractError(f"payload is not canonical JSON: {exc}") from exc
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise BehaviorContractError("payload exceeds the 1 MiB behavior limit")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class BehaviorCase:
    case_id: str
    input_sha256: str
    output_sha256: str
    evidence_id: str

    def __post_init__(self) -> None:
        for field in ("case_id", "evidence_id"):
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        object.__setattr__(self, "input_sha256", _digest(self.input_sha256, "input_sha256"))
        object.__setattr__(self, "output_sha256", _digest(self.output_sha256, "output_sha256"))


@dataclass(frozen=True, slots=True)
class BehaviorBaseline:
    target: str
    revision: str
    cases: tuple[BehaviorCase, ...]
    evidence: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _required_text(self.target, "target"))
        object.__setattr__(self, "revision", _required_text(self.revision, "revision"))
        if not isinstance(self.cases, (tuple, list)) or not 1 <= len(self.cases) <= _MAX_CASES:
            raise BehaviorContractError("baseline must contain between 1 and 1000 cases")
        if any(not isinstance(item, BehaviorCase) for item in self.cases):
            raise BehaviorContractError("baseline contains an invalid case")
        if not isinstance(self.evidence, (tuple, list)) or not 1 <= len(self.evidence) <= _MAX_EVIDENCE:
            raise BehaviorContractError("baseline must contain between 1 and 5000 evidence references")
        if any(not isinstance(item, EvidenceReference) for item in self.evidence):
            raise BehaviorContractError("baseline contains invalid evidence")
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise BehaviorContractError("baseline contains duplicate case IDs")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise BehaviorContractError("baseline contains duplicate evidence IDs")
        if any(item.evidence_id not in evidence_ids for item in self.cases):
            raise BehaviorContractError("baseline case references unknown evidence")
        object.__setattr__(self, "cases", tuple(self.cases))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "revision": self.revision,
            "cases": [
                {
                    "case_id": item.case_id,
                    "input_sha256": item.input_sha256,
                    "output_sha256": item.output_sha256,
                    "evidence_id": item.evidence_id,
                }
                for item in self.cases
            ],
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BehaviorBaseline":
        if not isinstance(data, Mapping) or set(data) != {"target", "revision", "cases", "evidence"}:
            raise BehaviorContractError("baseline must contain exactly target, revision, cases, and evidence")
        raw_cases = data["cases"]
        raw_evidence = data["evidence"]
        if not isinstance(raw_cases, (tuple, list)) or not isinstance(raw_evidence, (tuple, list)):
            raise BehaviorContractError("baseline cases and evidence must be arrays")
        cases: list[BehaviorCase] = []
        for item in raw_cases:
            if not isinstance(item, Mapping) or set(item) != {"case_id", "input_sha256", "output_sha256", "evidence_id"}:
                raise BehaviorContractError("baseline case has unknown or missing fields")
            try:
                cases.append(BehaviorCase(**dict(item)))
            except TypeError as exc:
                raise BehaviorContractError(f"invalid baseline case: {exc}") from exc
        evidence = tuple(
            item if isinstance(item, EvidenceReference) else EvidenceReference.from_dict(item)
            for item in raw_evidence
        )
        try:
            return cls(
                target=data["target"],
                revision=data["revision"],
                cases=tuple(cases),
                evidence=evidence,
            )
        except (KeyError, TypeError) as exc:
            raise BehaviorContractError(f"invalid baseline fields: {exc}") from exc


@dataclass(frozen=True, slots=True)
class BehaviorObservation:
    case_id: str
    input_sha256: str
    output_sha256: str
    status: ObservationStatus
    evidence_id: str

    def __post_init__(self) -> None:
        for field in ("case_id", "evidence_id"):
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        object.__setattr__(self, "input_sha256", _digest(self.input_sha256, "input_sha256"))
        object.__setattr__(self, "output_sha256", _digest(self.output_sha256, "output_sha256"))
        try:
            object.__setattr__(self, "status", ObservationStatus(self.status))
        except (TypeError, ValueError) as exc:
            raise BehaviorContractError(f"unsupported observation status: {exc}") from exc

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "status": self.status.value,
            "evidence_id": self.evidence_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BehaviorObservation":
        expected = {"case_id", "input_sha256", "output_sha256", "status", "evidence_id"}
        if not isinstance(data, Mapping) or set(data) != expected:
            raise BehaviorContractError("observation has unknown or missing fields")
        try:
            return cls(**dict(data))
        except TypeError as exc:
            raise BehaviorContractError(f"invalid observation fields: {exc}") from exc


@dataclass(frozen=True, slots=True)
class BehaviorComparison:
    verdict: BehaviorVerdict
    reasons: tuple[str, ...]
    matched_case_ids: tuple[str, ...] = ()
    missing_case_ids: tuple[str, ...] = ()
    unexpected_case_ids: tuple[str, ...] = ()
    changed_case_ids: tuple[str, ...] = ()
    verified_evidence_ids: tuple[str, ...] = ()

    @property
    def equivalent(self) -> bool:
        return self.verdict is BehaviorVerdict.EQUIVALENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "equivalent": self.equivalent,
            "reasons": list(self.reasons),
            "matched_case_ids": list(self.matched_case_ids),
            "missing_case_ids": list(self.missing_case_ids),
            "unexpected_case_ids": list(self.unexpected_case_ids),
            "changed_case_ids": list(self.changed_case_ids),
            "verified_evidence_ids": list(self.verified_evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class BehaviorGateDecision:
    """Combined assurance/behavior outcome; never grants execution or release authority."""

    verdict: "BehaviorGateVerdict"
    reasons: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return self.verdict is BehaviorGateVerdict.ASSURED

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
        }


class BehaviorGateVerdict(StrEnum):
    ASSURED = "assured"
    NEEDS_HUMAN = "needs_human"
    REJECTED = "rejected"


def evaluate_behavior_gate(
    assurance: AssuranceDecision,
    comparison: BehaviorComparison,
) -> BehaviorGateDecision:
    """Combine independent evidence assurance and behavior comparison.

    This is a review verdict only. It never authorizes code execution, merging,
    releasing, or deploying a change.
    """
    if not isinstance(assurance, AssuranceDecision) or not isinstance(comparison, BehaviorComparison):
        return BehaviorGateDecision(BehaviorGateVerdict.REJECTED, ("invalid gate input",))
    if assurance.verdict is AssuranceVerdict.REJECTED:
        return BehaviorGateDecision(
            BehaviorGateVerdict.REJECTED,
            ("evidence assurance rejected the result", *assurance.reasons),
        )
    if comparison.verdict in (BehaviorVerdict.INVALID, BehaviorVerdict.REGRESSION):
        return BehaviorGateDecision(
            BehaviorGateVerdict.REJECTED,
            ("behavior verification rejected the candidate", *comparison.reasons),
        )
    if (
        assurance.verdict is AssuranceVerdict.NEEDS_HUMAN
        or comparison.verdict is BehaviorVerdict.INCOMPLETE
    ):
        return BehaviorGateDecision(
            BehaviorGateVerdict.NEEDS_HUMAN,
            ("independent human review is required", *assurance.reasons, *comparison.reasons),
        )
    if assurance.verdict is AssuranceVerdict.ASSURED and comparison.verdict is BehaviorVerdict.EQUIVALENT:
        return BehaviorGateDecision(
            BehaviorGateVerdict.ASSURED,
            ("evidence assurance and recorded behavior comparison passed",),
        )
    return BehaviorGateDecision(BehaviorGateVerdict.REJECTED, ("unrecognized gate state",))


EvidenceVerifier = Callable[[EvidenceReference], bool]


def compare_behavior(
    baseline: BehaviorBaseline,
    observations: Sequence[BehaviorObservation],
    *,
    observation_evidence: Sequence[EvidenceReference],
    verify_evidence: EvidenceVerifier,
) -> BehaviorComparison:
    """Compare a candidate's recorded observations to a trusted baseline.

    Both baseline and candidate evidence are independently verified. No code
    execution occurs here. A harness must only submit observations from a
    separately authorized, isolated execution process.
    """
    if not isinstance(baseline, BehaviorBaseline):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("invalid baseline",))
    if not callable(verify_evidence):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("evidence verifier is required",))
    if not isinstance(observations, (tuple, list)) or len(observations) > _MAX_CASES:
        return BehaviorComparison(BehaviorVerdict.INVALID, ("invalid observation collection",))
    if not isinstance(observation_evidence, (tuple, list)):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("invalid observation evidence",))
    if any(not isinstance(item, BehaviorObservation) for item in observations):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("invalid observation item",))
    if any(not isinstance(item, EvidenceReference) for item in observation_evidence):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("invalid evidence item",))

    observed_ids = [item.case_id for item in observations]
    if len(observed_ids) != len(set(observed_ids)):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("duplicate observation case IDs",))
    if len(observation_evidence) > _MAX_EVIDENCE:
        return BehaviorComparison(BehaviorVerdict.INVALID, ("too many observation evidence references",))
    evidence_ids = [item.evidence_id for item in observation_evidence]
    baseline_evidence_ids = {item.evidence_id for item in baseline.evidence}
    if len(evidence_ids) != len(set(evidence_ids)):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("duplicate observation evidence IDs",))
    if baseline_evidence_ids.intersection(evidence_ids):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("baseline and observation evidence IDs must be distinct",))
    known_observation_evidence = set(evidence_ids)
    if any(item.evidence_id not in known_observation_evidence for item in observations):
        return BehaviorComparison(BehaviorVerdict.INVALID, ("observation references unknown evidence",))

    verified: list[str] = []
    for item in (*baseline.evidence, *observation_evidence):
        try:
            valid = verify_evidence(item)
        except Exception:
            valid = False
        if valid is not True:
            return BehaviorComparison(
                BehaviorVerdict.INVALID,
                (f"evidence verification failed: {item.evidence_id}",),
                verified_evidence_ids=tuple(verified),
            )
        verified.append(item.evidence_id)

    expected = {item.case_id: item for item in baseline.cases}
    actual = {item.case_id: item for item in observations}
    missing = tuple(sorted(set(expected) - set(actual)))
    unexpected = tuple(sorted(set(actual) - set(expected)))
    if unexpected:
        return BehaviorComparison(
            BehaviorVerdict.INVALID,
            ("observations contain cases outside the baseline",),
            missing_case_ids=missing,
            unexpected_case_ids=unexpected,
            verified_evidence_ids=tuple(verified),
        )
    if missing:
        return BehaviorComparison(
            BehaviorVerdict.INCOMPLETE,
            ("one or more baseline cases were not observed",),
            missing_case_ids=missing,
            verified_evidence_ids=tuple(verified),
        )

    matched: list[str] = []
    changed: list[str] = []
    input_mismatch: list[str] = []
    failed: list[str] = []
    not_run: list[str] = []
    for case_id, expected_case in expected.items():
        observed = actual[case_id]
        if observed.input_sha256 != expected_case.input_sha256:
            input_mismatch.append(case_id)
        elif observed.status is ObservationStatus.NOT_RUN:
            not_run.append(case_id)
        elif observed.status is ObservationStatus.FAILED:
            failed.append(case_id)
        elif observed.output_sha256 != expected_case.output_sha256:
            changed.append(case_id)
        else:
            matched.append(case_id)

    if input_mismatch:
        return BehaviorComparison(
            BehaviorVerdict.INVALID,
            ("input payload differs from the baseline case",),
            matched_case_ids=tuple(sorted(matched)),
            changed_case_ids=tuple(sorted(input_mismatch)),
            verified_evidence_ids=tuple(verified),
        )
    if failed or changed:
        return BehaviorComparison(
            BehaviorVerdict.REGRESSION,
            ("candidate behavior differs from the baseline",),
            matched_case_ids=tuple(sorted(matched)),
            changed_case_ids=tuple(sorted(set(failed + changed))),
            verified_evidence_ids=tuple(verified),
        )
    if not_run:
        return BehaviorComparison(
            BehaviorVerdict.INCOMPLETE,
            ("one or more candidate cases did not run",),
            matched_case_ids=tuple(sorted(matched)),
            missing_case_ids=tuple(sorted(not_run)),
            verified_evidence_ids=tuple(verified),
        )
    return BehaviorComparison(
        BehaviorVerdict.EQUIVALENT,
        ("all baseline cases produced matching, verified observations",),
        matched_case_ids=tuple(sorted(matched)),
        verified_evidence_ids=tuple(verified),
    )


__all__ = [
    "BehaviorBaseline", "BehaviorCase", "BehaviorComparison", "BehaviorContractError",
    "BehaviorGateDecision", "BehaviorGateVerdict", "BehaviorObservation", "BehaviorVerdict",
    "ObservationStatus", "compare_behavior", "digest_payload", "evaluate_behavior_gate",
]
