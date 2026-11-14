"""Fail-closed vulnerability confirmation.

A generic payload assembled from a source line cannot prove that the target
application is vulnerable. Until a target-aware verifier with an explicit,
reviewed contract is supplied, findings remain inconclusive.

This module deliberately does not execute generated probes. The legacy
probe_for API is retained only to fail loudly for callers that still rely on
the old self-confirming payloads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "CONFIRM_MARKERS", "VERDICTS", "Finding", "ProbeSandbox",
    "probe_for", "confirm", "patch_hint", "Verdict",
]

# Retained for compatibility with report consumers. These markers are NOT
# evidence and are never emitted by this module.
CONFIRM_MARKERS: dict[str, str] = {
    "sql_injection": "SQLI-PROOF",
    "xss": "XSS-PROOF",
    "cmd_injection": "CMD-PROOF",
    "path_traversal": "PATH-PROOF",
    "null_deref": "NPE-PROOF",
}
VERDICTS: tuple[str, ...] = ("confirmed", "refuted", "inconclusive")


class ProbeSandbox(Protocol):
    """Legacy sandbox interface; generic generated probes are no longer run."""

    def run_python(self, code: str, stdin: str = "") -> dict[str, Any]: ...


@dataclass(frozen=True)
class Finding:
    """One security observation emitted by a scanner."""

    rule: str
    path: str
    line: int
    kind: str
    code: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in CONFIRM_MARKERS:
            raise ValueError(
                f"نوع غير معروف: {self.kind} (المعروف: {sorted(CONFIRM_MARKERS)})"
            )


@dataclass(frozen=True)
class Verdict:
    """A bounded verdict with an explicit explanation and supporting evidence."""

    status: str
    detail: str
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.status not in VERDICTS:
            raise ValueError(f"حكم غير معروف: {self.status} (المعروف: {VERDICTS})")


def probe_for(finding: Finding) -> str:
    """Reject legacy synthetic probes: they cannot establish target behavior."""
    raise NotImplementedError(
        "تم تعطيل البروبات الاصطناعية: لا يمكنها إثبات سلوك التطبيق المستهدف"
    )


def confirm(
    finding: Finding,
    sandbox: ProbeSandbox | None,
    timeout_hint: int | None = None,
) -> Verdict:
    """Fail closed until a target-aware, independently validated verifier exists.

    The sandbox is intentionally not invoked. Running a payload constructed
    from a finding's source snippet can only demonstrate the payload itself,
    not that the application reaches or mishandles the vulnerable operation.
    """
    if sandbox is None:
        return Verdict(
            "inconclusive",
            "لا يوجد صندوق عزل؛ لم يُشغّل أي اختبار",
        )
    return Verdict(
        "inconclusive",
        "لا يوجد مدقّق واعٍ بسياق الهدف؛ لم يُشغّل أي بروب اصطناعي، "
        "ولا يمكن إصدار confirmed أو refuted",
    )


PATCH_HINTS: dict[str, str] = {
    "sql_injection": "مرّر القيم مُعامَلات لا بتنسيق نصي: cursor.execute(SQL, (value,))",
    "xss": "اسكِب المخرجات عند البناء (html.escape) أو استخدم قوالب تُسكّب تلقائياً",
    "cmd_injection": "مرّر الأمر قائمة أجزاء (shlex.split / subprocess(list)) ولا تنفذ نصاً مجمّعاً",
    "path_traversal": "قيّد المسار: Path(base).resolve() ثم تحقق أن الهدف داخل base",
    "null_deref": "افحص القيمة قبل الاستخدام: if value is None: … أو قيمة افتراضية",
}


def patch_hint(finding: Finding) -> str:
    """Return the declared remediation hint for a supported finding kind."""
    hint = PATCH_HINTS.get(finding.kind)
    if hint is None:
        raise ValueError(f"لا ترقيع معلن للنوع: {finding.kind}")
    return hint
