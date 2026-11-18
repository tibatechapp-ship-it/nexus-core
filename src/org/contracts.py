"""عقود التنظيم الهندسي الذاتي — أنواع البيانات التي تربط الأقسام الثمانية.

القواعد المعلنة المطبَّقة حرفيًا في هذا الملف:

1. **عقود مجمّدة** (``frozen``): لا تعديل موضعي بعد البناء — كل تغيير حالة
   يتم ببناء نسخة جديدة عبر ``dataclasses.replace`` أو دوال المتجر.
2. **تحقّق صريح في ``__post_init__``**: خطأ البناء رفع واضح لا تخمين صامت.
3. **آلة حالات المهمة مثبَّتة هنا وحدها**: ``ALLOWED_PHASE_TRANSITIONS`` هي
   المرجع الوحيد؛ أي انتقال خارجها رفع ``ValueError`` من المتجر.
4. **بوابة الدمج البشرية**: لا دمج ذاتي إطلاقًا — الدمج قرار ``Approval``
   بموافقة بشرية صريحة فقط، ويُفرض في المتجر و``pipeline``.
5. **الأدلة إلزامية**: ``Claim`` بلا ``evidence_ids`` لا يُقبل كمحقَّق؛
   ادعاء «محقَّق» بلا دليل مرفوض في البناء نفسه.
6. **التصنيف يُستعار من الطبقة التشغيلية** (``src.ops.contracts``):
   ``now_iso`` و``stable_id`` نفس المصدر — معرّفات حتمية عبر الموجتين.

الأقسام الثمانية (أدوار ``Department``):

* ``executive``     — المُنسّق التنفيذي (تفويض، صراع، تدقيق).
* ``repo_intel``    — ذكاء المستودع (معمارية، تبعيات، رسم معرفي).
* ``development``   — التطوير (backend/api/frontend/db/infra).
* ``code_review``   — المراجعة المستقلة (عدسات متعددة، إجماع).
* ``security``      — الأمن (أسرار، تبعيات، حقن، نمذجة تهديد).
* ``qa``            — الجودة (وحدات، تكامل، تغطية، انحدارات).
* ``verification``  — التحقق المستقل (أدلة، إعادة إنتاج، رفض غير المدعوم).
* ``release``       — هندسة الإصدار (فرع، رقعة، تقرير، تذكرة؛ لا دمج ذاتي).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from src.ops.contracts import now_iso, stable_id

__all__ = [
    "ALLOWED_PHASE_TRANSITIONS",
    "APPROVAL_KINDS",
    "DEPARTMENTS",
    "DEV_KINDS",
    "EVIDENCE_KINDS",
    "FINAL_PHASES",
    "MISSION_PHASES",
    "MISSION_STATUSES",
    "REVIEW_LENSES",
    "REVIEW_VERDICTS",
    "SEVERITIES",
    "TASK_STATES",
    "Approval",
    "Claim",
    "Evidence",
    "Finding",
    "Lesson",
    "Mission",
    "Review",
    "TaskResult",
    "TaskSpec",
    "new_id",
]

# ── الآلات المعلنة ────────────────────────────────────────────────────────

#: أطوار المهمة — خط الأنابيب A→G كما هو معلن في مخطط التنظيم.
MISSION_PHASES: tuple[str, ...] = (
    "A_REQUIREMENTS",
    "B_INTEL",
    "C_DEVELOP",
    "D_REVIEW",
    "E_TESTING",
    "F_VERIFICATION",
    "G_RELEASE",
)

#: الأطوار النهائية — لا انتقال منها إلا ببناء مهمة جديدة.
FINAL_PHASES: frozenset[str] = frozenset({"G_RELEASE", "FAILED", "CANCELLED"})

#: الانتقالات القانونية — المرجع الوحيد لآلة أطوار المهمة.
ALLOWED_PHASE_TRANSITIONS: dict[str, frozenset[str]] = {
    "A_REQUIREMENTS": frozenset({"B_INTEL", "FAILED", "CANCELLED"}),
    "B_INTEL": frozenset({"C_DEVELOP", "FAILED", "CANCELLED"}),
    "C_DEVELOP": frozenset({"D_REVIEW", "FAILED", "CANCELLED"}),
    "D_REVIEW": frozenset({"E_TESTING", "C_DEVELOP", "FAILED", "CANCELLED"}),
    # الدورة المراجعة→تطوير مقيّدة بعدد دورات المراجعة (سقف معلن في الإعدادات)
    "E_TESTING": frozenset({"F_VERIFICATION", "FAILED", "CANCELLED"}),
    "F_VERIFICATION": frozenset({"G_RELEASE", "D_REVIEW", "FAILED", "CANCELLED"}),
    "G_RELEASE": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}

#: حالات المهمة العليا — مستقلة عن الطور.
MISSION_STATUSES: tuple[str, ...] = (
    "created", "running", "done", "failed", "cancelled")

#: حالات المهمة الفرعية في الرسم (DAG).
TASK_STATES: tuple[str, ...] = ("pending", "running", "done", "failed", "skipped")

#: الأقسام الثمانية — أدوار معلنة لا اختراع وقت التشغيل.
DEPARTMENTS: tuple[str, ...] = (
    "executive",
    "repo_intel",
    "development",
    "code_review",
    "security",
    "qa",
    "verification",
    "release",
)

#: أنواع مهام التطوير — كل نوع وكيل تطوير مستقل.
DEV_KINDS: tuple[str, ...] = ("backend", "api", "frontend", "db", "infra")

#: عدسات المراجعة المستقلة — كل عدسة مراجع مستقل بحد ذاته.
REVIEW_LENSES: tuple[str, ...] = (
    "logic",
    "architecture",
    "security",
    "performance",
    "regression",
    "maintainability",
)

#: أحكام المراجعة.
REVIEW_VERDICTS: tuple[str, ...] = ("approve", "request_changes")

#: درجات الخطورة المعلنة.
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

#: أنواع الأدلة المقبولة — دليل بلا نوع معلن مرفوض.
EVIDENCE_KINDS: tuple[str, ...] = (
    "test_result",
    "diff",
    "scan",
    "replay",
    "log",
    "static_analysis",
)

#: أنواع الموافقات — كل قرار حسّاس له نوع معلن.
APPROVAL_KINDS: tuple[str, ...] = ("merge", "modify", "run_untrusted")


def _require_str(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} يجب أن يكون نصًا غير فارغ، وليس: {value!r}")


def _require_in(value: Any, name: str,
                allowed: tuple[str, ...] | frozenset[str]) -> None:
    _require_str(value, name)
    if value not in allowed:
        raise ValueError(f"{name} يجب أن يكون من {allowed}، وليس: {value!r}")


def _require_list(value: Any, name: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{name} يجب أن يكون قائمة، وليس: {value!r}")


# ── المهمة العليا ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mission:
    """مهمة هندسية واحدة — وحدة العمل العليا للتنظيم كله.

    ``phase`` يتحرك عبر آلة الحالات المعلنة أعلاه فقط؛ المتجر هو من
    يفرض الانتقال. ``ticket_ids`` تذاكر الطبقة التشغيلية المرتبطة —
    الدمج النهائي عبرها وبوابة بشرية، لا عبر هذا العقد.
    """

    title: str
    objective: str
    repo_path: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    phase: str = "A_REQUIREMENTS"
    status: str = "created"
    branch: str = ""
    patch_path: str = ""
    report_path: str = ""
    ticket_ids: list[str] = field(default_factory=list)
    revision_loops: int = 0
    id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    output_token_limit: int | None = None

    def __post_init__(self) -> None:
        _require_str(self.title, "title")
        _require_str(self.objective, "objective")
        _require_in(self.phase, "phase", tuple(ALLOWED_PHASE_TRANSITIONS))
        _require_in(self.status, "status", MISSION_STATUSES)
        _require_list(self.acceptance_criteria, "acceptance_criteria")
        _require_list(self.constraints, "constraints")
        _require_list(self.ambiguities, "ambiguities")
        _require_list(self.ticket_ids, "ticket_ids")
        if not isinstance(self.revision_loops, int) or self.revision_loops < 0:
            raise ValueError(f"revision_loops غير صالح: {self.revision_loops!r}")
        if self.output_token_limit is not None and (
                type(self.output_token_limit) is not int
                or self.output_token_limit <= 0
                or self.output_token_limit > 2**63 - 1):
            raise ValueError("output_token_limit يجب أن يكون عدد توكنات موجبًا ضمن حد SQLite")

    def with_phase(self, phase: str) -> "Mission":
        """نسخة بطور جديد — الانتقال نفسه يُفرض في المتجر لا هنا."""
        return replace(self, phase=phase, updated_at=now_iso())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "objective": self.objective,
            "repo_path": self.repo_path,
            "acceptance_criteria": self.acceptance_criteria,
            "constraints": self.constraints, "ambiguities": self.ambiguities,
            "phase": self.phase, "status": self.status, "branch": self.branch,
            "patch_path": self.patch_path, "report_path": self.report_path,
            "ticket_ids": self.ticket_ids, "revision_loops": self.revision_loops,
            "output_token_limit": self.output_token_limit,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mission":
        return cls(
            title=data["title"], objective=data["objective"],
            repo_path=data.get("repo_path", ""),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            constraints=list(data.get("constraints", [])),
            ambiguities=list(data.get("ambiguities", [])),
            phase=data.get("phase", "A_REQUIREMENTS"),
            status=data.get("status", "created"),
            branch=data.get("branch", ""), patch_path=data.get("patch_path", ""),
            report_path=data.get("report_path", ""),
            ticket_ids=list(data.get("ticket_ids", [])),
            revision_loops=int(data.get("revision_loops", 0)),
            output_token_limit=data.get("output_token_limit"),
            id=data.get("id", ""),
            created_at=data.get("created_at", now_iso()),
            updated_at=data.get("updated_at", now_iso()),
        )


# ── مهام الرسم (DAG) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskSpec:
    """مهمة فرعية في رسم التنفيذ — عقد إدخال لوكيل قسم محدد.

    ``deps`` معرّفات مهام يجب أن تنتهي بنجاح قبل بدء هذه المهمة؛
    الدورة في الرسم مرفوضة في البناء نفسه.
    """

    mission_id: str
    dept: str
    kind: str                      # نوع العمل داخل القسم (مثل lens أو dev kind)
    description: str
    deps: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.mission_id, "mission_id")
        _require_in(self.dept, "dept", DEPARTMENTS)
        _require_str(self.kind, "kind")
        _require_str(self.description, "description")
        _require_list(self.deps, "deps")
        if not isinstance(self.params, dict):
            raise ValueError(f"params يجب أن يكون قاموسًا، وليس: {self.params!r}")

    def with_id(self, task_id: str) -> "TaskSpec":
        return replace(self, id=task_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "mission_id": self.mission_id, "dept": self.dept,
            "kind": self.kind, "description": self.description,
            "deps": self.deps, "params": self.params,
        }


@dataclass(frozen=True)
class TaskResult:
    """ناتج مهمة فرعية — كل ناتج يحمل استهلاكه ومحاولاته وسجله."""

    task_id: str
    dept: str
    status: str                    # TASK_STATES
    output: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    error: str = ""
    log_ref: str = ""

    def __post_init__(self) -> None:
        _require_str(self.task_id, "task_id")
        _require_in(self.dept, "dept", DEPARTMENTS)
        _require_in(self.status, "status", TASK_STATES)
        if not isinstance(self.output, dict):
            raise ValueError(f"output يجب أن يكون قاموسًا، وليس: {self.output!r}")
        if self.attempts < 1:
            raise ValueError(f"attempts يجب أن يكون ≥ 1، وليس: {self.attempts!r}")


# ── المراجعة والنتائج ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Review:
    """مراجعة مستقلة واحدة — عدسة واحدة ومراجع واحد لكل سجل.

    الاستقلال معلن: مراجع لا يوافق على تعديله هو — ``reviewer`` يجب أن
    يختلف عن دور مطوّر المهمة (يُفرض في المجلس لا هنا).
    """

    mission_id: str
    task_id: str
    reviewer: str                  # اسم المراجع المستقل (دور/عدسة)
    lens: str
    verdict: str                   # approve | request_changes
    score: int                     # 0..100
    comments: str = ""
    issues: list[dict[str, Any]] = field(default_factory=list)
    debate_round: int = 0
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.mission_id, "mission_id")
        _require_str(self.task_id, "task_id")
        _require_str(self.reviewer, "reviewer")
        _require_in(self.lens, "lens", REVIEW_LENSES)
        _require_in(self.verdict, "verdict", REVIEW_VERDICTS)
        if not isinstance(self.score, int) or not 0 <= self.score <= 100:
            raise ValueError(f"score يجب أن يكون عددًا 0..100، وليس: {self.score!r}")
        _require_list(self.issues, "issues")
        if not isinstance(self.debate_round, int) or self.debate_round < 0:
            raise ValueError(f"debate_round غير صالح: {self.debate_round!r}")


@dataclass(frozen=True)
class Finding:
    """نتيجة فحص واحدة — من الأمن أو المراجعة أو الجودة أو الذكاء."""

    mission_id: str
    source: str                    # security | review | qa | repo_intel | verification
    category: str
    severity: str
    description: str
    file: str = ""
    line: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    status: str = "open"           # open | fixed | wontfix
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.mission_id, "mission_id")
        _require_str(self.source, "source")
        _require_str(self.category, "category")
        _require_in(self.severity, "severity", SEVERITIES)
        _require_str(self.description, "description")
        _require_list(self.evidence_ids, "evidence_ids")
        if self.status not in ("open", "fixed", "wontfix"):
            raise ValueError(f"status غير صالح: {self.status!r}")


# ── الادعاءات والأدلة ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Claim:
    """ادعاء واحد من وكيل — لا يُصدَّق إلا بالأدلة.

    الحالة الافتراضية ``unverified``: قول بلا دليل ليس حقيقة، ومحاولته
    تمريره كـ``verified`` بلا ``evidence_ids`` مرفوضة في العقد نفسه.
    """

    mission_id: str
    agent_role: str
    statement: str
    claim_kind: str = "observation"  # observation | fix | test_pass | no_regression
    status: str = "unverified"       # unverified | verified | rejected | inconclusive
    evidence_ids: list[str] = field(default_factory=list)
    resolution: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.mission_id, "mission_id")
        _require_str(self.agent_role, "agent_role")
        _require_str(self.statement, "statement")
        _require_in(self.status, "status",
                    ("unverified", "verified", "rejected", "inconclusive"))
        _require_list(self.evidence_ids, "evidence_ids")
        if self.status == "verified" and not self.evidence_ids:
            raise ValueError("ادعاء محقَّق بلا أدلة مرفوض — لا تصديق شفوي")


@dataclass(frozen=True)
class Evidence:
    """دليل واحد قابل لإعادة الإنتاج — الاختبار/الرقعة/المسح/السجل."""

    mission_id: str
    kind: str                      # EVIDENCE_KINDS
    detail: dict[str, Any] = field(default_factory=dict)
    captured_by: str = ""
    ok: bool = True
    claim_id: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.mission_id, "mission_id")
        _require_in(self.kind, "kind", EVIDENCE_KINDS)
        if not isinstance(self.detail, dict):
            raise ValueError(f"detail يجب أن يكون قاموسًا، وليس: {self.detail!r}")
        if not isinstance(self.ok, bool):
            raise ValueError(f"ok يجب أن يكون منطقيًا، وليس: {self.ok!r}")

    def summary(self) -> str:
        """سطر ملخص حتمي — نفس الدليل يعطي نفس السطر."""
        ok_txt = "نجح" if self.ok else "فشل"
        keys = ",".join(sorted(self.detail)) if self.detail else "-"
        return f"[{self.kind}] {ok_txt} ({keys}) بواسطة {self.captured_by or 'غير معلوم'}"


# ── الموافقات البشرية ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Approval:
    """طلب موافقة بشرية — الدمج والتعديل الحسّاس وتشغيل كود غير موثوق.

    ``approved`` يبدأ ``None`` (قيد الانتظار)؛ قرار بدون ``decided_by``
    نص غير فارغ مرفوض — لا موافقات مجهولة.
    """

    mission_id: str
    kind: str                      # APPROVAL_KINDS
    subject: str                   # ما تخصّص الموافقة (تذكرة/فرع/أمر)
    note: str = ""
    approved: bool | None = None
    decided_by: str = ""
    decided_at: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.mission_id, "mission_id")
        _require_in(self.kind, "kind", APPROVAL_KINDS)
        _require_str(self.subject, "subject")
        if self.approved is not None:
            if not isinstance(self.approved, bool):
                raise ValueError(
                    f"approved يجب أن يكون منطقيًا، وليس: {self.approved!r}")
            _require_str(self.decided_by, "decided_by")
            if self.approved and not self.decided_at:
                raise ValueError("قرار الموافقة يحتاج طابعًا زمنيًا للقرار")

    def decide(self, approved: bool, decided_by: str) -> "Approval":
        """نسخة بقرار جديد — القرار نفسه يُفرض في المتجر."""
        return replace(self, approved=approved, decided_by=decided_by,
                       decided_at=now_iso() if approved else self.decided_at)


# ── الدروس ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Lesson:
    """درس هندسي موثَّق — من نتائج التحقق والمراجعة، بثقة معلنة.

    الدرس لا يعدّل سياسة أمنية ولا يمنح صلاحية: ``scope`` وصفية فقط،
    ومحرك التخطيط يقرأه اقتراحًا لا أمرًا.
    """

    text: str
    scope: str                     # دور/طور/نوع مستودع
    confidence: float = 0.5
    source_mission_id: str = ""
    applied_count: int = 0
    active: bool = True
    id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.text, "text")
        _require_str(self.scope, "scope")
        if not isinstance(self.confidence, float) \
                or not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence يجب أن يكون 0.0..1.0، وليس: {self.confidence!r}")
        if not isinstance(self.applied_count, int) or self.applied_count < 0:
            raise ValueError(f"applied_count غير صالح: {self.applied_count!r}")

    def bumped(self) -> "Lesson":
        """نسخة بعدد تطبيق أعلى — يزيد ترتيبها في التخطيط."""
        return replace(self, applied_count=self.applied_count + 1)


def new_id(prefix: str, *parts: str) -> str:
    """معرّف حتمي مسبوق ببادئة قابلة للقراءة (مثل ``org-m`` للمهام).

    نفس المحتوى يعطي نفس المعرّف في كل تشغيل — أساس إزالة التكرار
    وقابلية إعادة الإنتاج في الاختبارات والتقارير.
    """
    _require_str(prefix, "prefix")
    body = stable_id(*parts) if parts else stable_id(now_iso(), prefix)
    return f"{prefix}-{body}"
