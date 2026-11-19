"""Versioned, bounded contracts shared by intelligence and assurance engines.

The contract deliberately stores evidence references and digests, not source
contents. Engine-specific scanners remain independent and may be unavailable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


CONTRACT_VERSION = "nexus.intelligence/v1"
MAX_TEXT_LENGTH = 4096
MAX_FINDINGS = 1000
MAX_EVIDENCE = 5000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when an intelligence payload violates the public contract."""


class ResultStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    REJECTED = "rejected"
    FAILED = "failed"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    INCONCLUSIVE = "inconclusive"
    FALSE_POSITIVE = "false_positive"
    REMEDIATED = "remediated"


def _text(value: Any, field: str, *, limit: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ContractError(f"{field} must not be empty")
    if len(value) > limit:
        raise ContractError(f"{field} exceeds {limit} characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise ContractError(f"{field} contains control characters")
    return value


def _strings(value: Any, field: str, *, limit: int = 256) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ContractError(f"{field} must be a list or tuple of strings")
    if len(value) > limit:
        raise ContractError(f"{field} exceeds {limit} items")
    result = tuple(_text(item, field) for item in value)
    if len(set(result)) != len(result):
        raise ContractError(f"{field} contains duplicates")
    return result


def _strict_keys(data: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ContractError(f"{field} contains unknown fields: {', '.join(sorted(unknown))}")


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """A bounded pointer to independently retrievable evidence."""

    evidence_id: str
    kind: str
    locator: str
    sha256: str
    collected_by: str

    def __post_init__(self) -> None:
        for field in ("evidence_id", "kind", "locator", "collected_by"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ContractError("sha256 must be a lowercase 64-character SHA-256 digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "locator": self.locator,
            "sha256": self.sha256,
            "collected_by": self.collected_by,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvidenceReference:
        if not isinstance(data, Mapping):
            raise ContractError("evidence must be an object")
        _strict_keys(data, {"evidence_id", "kind", "locator", "sha256", "collected_by"}, "evidence")
        try:
            return cls(**dict(data))
        except TypeError as exc:
            raise ContractError(f"invalid evidence fields: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Finding:
    """One bounded finding with explicit confidence and evidence linkage."""

    finding_id: str
    rule_id: str
    severity: Severity
    confidence: float
    summary: str
    status: FindingStatus
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("finding_id", "rule_id", "summary"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        try:
            object.__setattr__(self, "severity", Severity(self.severity))
            object.__setattr__(self, "status", FindingStatus(self.status))
        except ValueError as exc:
            raise ContractError(f"unsupported finding classification: {exc}") from exc
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ContractError("confidence must be a number between 0 and 1")
        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ContractError("confidence must be a finite number between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        if self.status is FindingStatus.CONFIRMED and not self.evidence_ids:
            raise ContractError("confirmed findings require at least one evidence reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "summary": self.summary,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Finding:
        if not isinstance(data, Mapping):
            raise ContractError("finding must be an object")
        _strict_keys(
            data,
            {"finding_id", "rule_id", "severity", "confidence", "summary", "status", "evidence_ids"},
            "finding",
        )
        payload = dict(data)
        payload["evidence_ids"] = payload.get("evidence_ids", ())
        try:
            return cls(**payload)
        except TypeError as exc:
            raise ContractError(f"invalid finding fields: {exc}") from exc


@dataclass(frozen=True, slots=True)
class IntelligenceResult:
    """Immutable, versioned output shared by analysis engines and the gate."""

    mission_id: str
    run_id: str
    engine: str
    target: str
    scope: tuple[str, ...]
    status: ResultStatus
    findings: tuple[Finding, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    limitations: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        for field in ("mission_id", "run_id", "engine", "target", "contract_version"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        if self.contract_version != CONTRACT_VERSION:
            raise ContractError(f"unsupported contract_version: {self.contract_version}")
        try:
            object.__setattr__(self, "status", ResultStatus(self.status))
        except ValueError as exc:
            raise ContractError(f"unsupported result status: {self.status}") from exc

        for field, limit in (("scope", 256), ("limitations", 256), ("recommendations", 256)):
            object.__setattr__(self, field, _strings(getattr(self, field), field, limit=limit))

        for field, limit, item_type in (
            ("findings", MAX_FINDINGS, Finding),
            ("evidence", MAX_EVIDENCE, EvidenceReference),
        ):
            items = getattr(self, field)
            if not isinstance(items, (list, tuple)) or len(items) > limit:
                raise ContractError(f"{field} must be a sequence with at most {limit} items")
            if any(not isinstance(item, item_type) for item in items):
                raise ContractError(f"{field} contains an invalid item")
            object.__setattr__(self, field, tuple(items))

        if not self.scope:
            raise ContractError("scope must identify at least one authorized target")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ContractError("evidence contains duplicate evidence_id values")
        finding_ids = [item.finding_id for item in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ContractError("findings contains duplicate finding_id values")
        known_evidence = set(evidence_ids)
        for finding in self.findings:
            missing = set(finding.evidence_ids) - known_evidence
            if missing:
                raise ContractError(
                    f"finding {finding.finding_id} references unknown evidence: "
                    + ", ".join(sorted(missing))
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "mission_id": self.mission_id,
            "run_id": self.run_id,
            "engine": self.engine,
            "target": self.target,
            "scope": list(self.scope),
            "status": self.status.value,
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "limitations": list(self.limitations),
            "recommendations": list(self.recommendations),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IntelligenceResult:
        if not isinstance(data, Mapping):
            raise ContractError("result must be an object")
        _strict_keys(
            data,
            {
                "contract_version", "mission_id", "run_id", "engine", "target", "scope",
                "status", "findings", "evidence", "limitations", "recommendations",
            },
            "result",
        )
        payload = dict(data)
        try:
            payload["findings"] = tuple(
                item if isinstance(item, Finding) else Finding.from_dict(item)
                for item in payload.get("findings", ())
            )
            payload["evidence"] = tuple(
                item if isinstance(item, EvidenceReference) else EvidenceReference.from_dict(item)
                for item in payload.get("evidence", ())
            )
            return cls(**payload)
        except TypeError as exc:
            raise ContractError(f"invalid result fields: {exc}") from exc


__all__ = [
    "CONTRACT_VERSION",
    "MAX_EVIDENCE",
    "MAX_FINDINGS",
    "ContractError",
    "EvidenceReference",
    "Finding",
    "FindingStatus",
    "IntelligenceResult",
    "ResultStatus",
    "Severity",
]
