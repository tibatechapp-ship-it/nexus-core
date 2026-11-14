"""العقود الموحّدة — أنواع البيانات الخمسة التي تربط مكوّنات الطبقة التشغيلية.

كل مكوّن (رادار/فهرس/عزل/تذاكر/فحوص ويب) يكتب ويقرأ هذه الأنواع فقط؛
ما يجعل اللوحة والتقارير موحّدة دون كود لصق. كل عقد:

* بيانات مجمّدة (``frozen``) — لا تعديل موضعي بعد البناء.
* تحقّق صريح في ``__post_init__`` — خطأ البناء رفع واضح لا تخمين.
* معرّف حتمي (``stable_id``) من محتواه — نفس المحتوى يعطي نفس المعرّف.
* تحويل dict ذهابًا وإيابًا (``to_dict`` / ``from_dict``) للتخزين والتلخيص.

آلة حالات التذكرة مثبَّتة هنا وحدها: ``ALLOWED_TRANSITIONS`` هي المرجع
الوحيد، وقاعدة الدمج (مراجعة بشرية + CI أخضر) تُفرض في ``store`` و``tickets``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "ALLOWED_TRANSITIONS",
    "FINAL_STATES",
    "ORIGINS",
    "TICKET_STATES",
    "VERDICTS",
    "Digest",
    "GateResult",
    "Signal",
    "Ticket",
    "Verdict",
    "now_iso",
    "stable_id",
]

#: حالات التذكرة الثابتة — خطأ الحالة رفع صريح لا تخمين.
TICKET_STATES: tuple[str, ...] = (
    "open",
    "branched",
    "executed",
    "reported",
    "reviewed",
    "merged",
    "closed",
)

#: الانتقالات القانونية — المرجع الوحيد لآلة الحالات.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"branched", "closed"}),
    "branched": frozenset({"executed", "closed"}),
    "executed": frozenset({"reported", "closed"}),
    "reported": frozenset({"reviewed", "closed"}),
    "reviewed": frozenset({"merged", "closed"}),
    "merged": frozenset(),
    "closed": frozenset(),
}

#: الحالات النهائية — تذاكر لا تُغلق تلقائيًا كعفاة ولا تُعدّ ناشطة.
FINAL_STATES: frozenset[str] = frozenset({"merged", "closed"})

#: أحكام العزل الثلاثية — الافتراضي ``inconclusive`` (صادق عند نقص الأدلة).
VERDICTS: tuple[str, ...] = ("confirmed", "safe", "inconclusive")

#: مصادر التذكرة — من أين جاء الحدث المفتاحي.
ORIGINS: tuple[str, ...] = ("radar", "sandbox", "webqa", "manual")


def now_iso() -> str:
    """الوقت الحالي بتوقيت UTC بصيغة ISO-8601 — نقطة زمن واحدة للعقود كلها."""
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str) -> str:
    """معرّف حتمي من المحتوى — أول 12 خانة من SHA-256 للمُدخلات المجمّعة.

    لا ``hash()`` ولا عشوائية: نفس المحتوى يعطي نفس المعرّف في كل تشغيل،
    وهو أساس إزالة التكرار في الرادار والتخزين الإلزامي (idempotent).
    """
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def _require_str(value: Any, name: str) -> str:
    """تحقّق نص واحد — القيمة نصية وغير فارغة، وإلا خطأ صريح."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} يجب أن يكون نصًا غير فارغ، وليس: {value!r}")
    return value


def _require_in(value: Any, name: str, known: tuple[str, ...]) -> str:
    """تحقّق عضوية — القيمة من الثوابت المعلنة فقط."""
    _require_str(value, name)
    if value not in known:
        raise ValueError(f"{name} غير معروف: {value!r} (المعروف: {known})")
    return value


def _require_confidence(value: Any) -> float:
    """الثقة رقم بين 0 و1 — خارج المدى خطأ، لأن الرقم بلا مدى بلا معنى."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"confidence يجب أن يكون رقمًا، وليس: {value!r}")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"confidence خارج المدى [0,1]: {value!r}")
    return float(value)


@dataclass(frozen=True)
class Signal:
    """إشارة واحدة من الرادار — العقد الموحّد لكل ما يُرصد من المصادر.

    ``id`` حتمي من (المصدر + الرابط): الإشارة نفسها تُنتج معرّفًا واحدًا
    في كل تشغيل، وهو ما يجعل إزالة التكرار ممكنة دون جداول إضافية.
    """

    source: str
    title: str
    url: str
    published_at: str = ""
    score: float = 0.0
    tags: tuple[str, ...] = ()
    raw_ref: str = ""
    id: str = ""
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _require_str(self.source, "source")
        _require_str(self.title, "title")
        _require_str(self.url, "url")
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            raise ValueError(f"score يجب أن يكون رقمًا، وليس: {self.score!r}")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "tags", tuple(str(t) for t in self.tags))
        if not self.id:
            object.__setattr__(self, "id", stable_id(self.source, self.url))

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي — نفس المفاتيح في كل مكان يُخزَّن أو يُعرض."""
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "score": self.score,
            "tags": list(self.tags),
            "raw_ref": self.raw_ref,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """البناء من التمثيل القياسي — المفاتيح الناقصة تعود لافتراضاتها."""
        return cls(
            source=data["source"],
            title=data["title"],
            url=data["url"],
            published_at=str(data.get("published_at", "")),
            score=float(data.get("score", 0.0)),
            tags=tuple(data.get("tags", ())),
            raw_ref=str(data.get("raw_ref", "")),
            id=str(data.get("id", "")),
            created_at=str(data.get("created_at", "")) or now_iso(),
        )


@dataclass(frozen=True)
class Verdict:
    """حكم العزل الثلاثي — نتيجة فحص هدف داخل العزل مع الأدلة.

    الافتراضي ``inconclusive``: نقص الأدلة ليس أمانًا ولا خطرًا — إنه
    «غير محسوم»، ولا تذكرة تُفتح إلا لـ ``confirmed`` و``inconclusive``.
    """

    target: str
    verdict: str = "inconclusive"
    evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    checks: dict[str, str] = field(default_factory=dict)
    ticket_id: str | None = None
    id: str = ""
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _require_str(self.target, "target")
        _require_in(self.verdict, "verdict", VERDICTS)
        if not self.evidence:
            raise ValueError("الحكم بلا أدلة مرفوض — require_evidence شرط مثبّت")
        object.__setattr__(self, "evidence", tuple(str(e) for e in self.evidence))
        object.__setattr__(self, "confidence", _require_confidence(self.confidence))
        if not isinstance(self.checks, dict):
            raise ValueError(f"checks يجب أن يكون قاموسًا، وليس: {self.checks!r}")
        if not self.id:
            object.__setattr__(self, "id", stable_id(self.target, self.verdict))

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للحكم — الأدلة قائمة والفحوص قاموس نص/نص."""
        return {
            "id": self.id,
            "target": self.target,
            "verdict": self.verdict,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "checks": dict(self.checks),
            "ticket_id": self.ticket_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Verdict:
        """البناء من التمثيل القياسي — الحكم بلا أدلة مرفوض هنا أيضًا."""
        return cls(
            target=data["target"],
            verdict=str(data.get("verdict", "inconclusive")),
            evidence=tuple(data.get("evidence", ())),
            confidence=float(data.get("confidence", 0.0)),
            checks=dict(data.get("checks", {})),
            ticket_id=data.get("ticket_id"),
            id=str(data.get("id", "")),
            created_at=str(data.get("created_at", "")) or now_iso(),
        )

    @property
    def needs_ticket(self) -> bool:
        """هل يفتح هذا الحكم تذكرة؟ — المؤكَّد وغير المحسوم فقط."""
        return self.verdict in {"confirmed", "inconclusive"}


@dataclass(frozen=True)
class Ticket:
    """تذكرة واحدة — العقد الموحّد لكل حدث يستحق مسار عمل كاملًا.

    ``publish_allowed=False`` افتراضيًا: النشر/الدمج محجوب حتى مراجعة
    بشرية صريحة، والفرع ``t/<id>`` اسم معلن منذ اللحظة الأولى.
    """

    origin: str
    title: str
    branch: str = ""
    state: str = "open"
    report: dict[str, Any] = field(default_factory=dict)
    publish_allowed: bool = False
    id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _require_in(self.origin, "origin", ORIGINS)
        _require_str(self.title, "title")
        _require_in(self.state, "state", TICKET_STATES)
        if not isinstance(self.report, dict):
            raise ValueError(f"report يجب أن يكون قاموسًا، وليس: {self.report!r}")
        if not isinstance(self.publish_allowed, bool):
            raise ValueError(
                f"publish_allowed يجب أن يكون منطقيًا، وليس: {self.publish_allowed!r}"
            )
        if not self.branch:
            object.__setattr__(self, "branch", f"t/{self.id}" if self.id else "")

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للتذكرة — التقرير قاموس كما أُنشئ."""
        return {
            "id": self.id,
            "origin": self.origin,
            "title": self.title,
            "branch": self.branch,
            "state": self.state,
            "report": dict(self.report),
            "publish_allowed": self.publish_allowed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Ticket:
        """البناء من التمثيل القياسي — الحالة من الثوابت فقط."""
        return cls(
            origin=data["origin"],
            title=data["title"],
            branch=str(data.get("branch", "")),
            state=str(data.get("state", "open")),
            report=dict(data.get("report", {})),
            publish_allowed=bool(data.get("publish_allowed", False)),
            id=str(data.get("id", "")),
            created_at=str(data.get("created_at", "")) or now_iso(),
            updated_at=str(data.get("updated_at", "")) or now_iso(),
        )


@dataclass(frozen=True)
class GateResult:
    """نتيجة بوابة فحص — من فحوص الويب أو أي بوابة CI مستقبلية.

    ``blocking=False`` يعني بوابة استشارية: تُسجَّل وتُعرض ولا تمنع الدمج.
    """

    tool: str
    target: str
    blocking: bool = False
    passed: bool = True
    findings: tuple[dict[str, str], ...] = ()
    ticket_id: str | None = None
    id: str = ""
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _require_str(self.tool, "tool")
        _require_str(self.target, "target")
        if not isinstance(self.blocking, bool) or not isinstance(self.passed, bool):
            raise ValueError("blocking و passed يجب أن يكونا منطقيين")
        if not isinstance(self.findings, tuple):
            object.__setattr__(self, "findings", tuple(self.findings))
        if not self.passed and not self.findings:
            raise ValueError("بوابة فاشلة بلا نتائج مرفوضة — الأدلة شرط")
        if not self.id:
            object.__setattr__(
                self, "id", stable_id(self.tool, self.target, str(self.created_at))
            )

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للبوابة — النتائج قائمة قواميس."""
        return {
            "id": self.id,
            "tool": self.tool,
            "target": self.target,
            "blocking": self.blocking,
            "passed": self.passed,
            "findings": [dict(f) for f in self.findings],
            "ticket_id": self.ticket_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateResult:
        """البناء من التمثيل القياسي — فشل بلا نتائج مرفوض هنا أيضًا."""
        return cls(
            tool=data["tool"],
            target=data["target"],
            blocking=bool(data.get("blocking", False)),
            passed=bool(data.get("passed", True)),
            findings=tuple(dict(f) for f in data.get("findings", ())),
            ticket_id=data.get("ticket_id"),
            id=str(data.get("id", "")),
            created_at=str(data.get("created_at", "")) or now_iso(),
        )


@dataclass(frozen=True)
class Digest:
    """ملخص واحد — العقد الموحّد للتقارير الصامتة (صباح/مساء/دورة تشغيل).

    الملخص الواحد هو مفتاح «منع الإزعاج»: لا إشعار لكل عنصر، بل نص واحد
    حتمي يُبنى من المخزن ويُعرض في اللوحة والقناة الواحدة.
    """

    kind: str
    day: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        _require_in(self.kind, "kind", ("morning", "evening", "cycle"))
        _require_str(self.day, "day")
        if not isinstance(self.payload, dict):
            raise ValueError(f"payload يجب أن يكون قاموسًا، وليس: {self.payload!r}")
        if not self.id:
            object.__setattr__(self, "id", stable_id(self.kind, self.day))

    def to_dict(self) -> dict[str, Any]:
        """التمثيل القياسي للملخص — الحمولة قاموس كما بُنيت."""
        return {
            "id": self.id,
            "kind": self.kind,
            "day": self.day,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Digest:
        """البناء من التمثيل القياسي — النوع من الثوابت فقط."""
        return cls(
            kind=data["kind"],
            day=data["day"],
            payload=dict(data.get("payload", {})),
            id=str(data.get("id", "")),
            created_at=str(data.get("created_at", "")) or now_iso(),
        )
