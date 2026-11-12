"""عقد الحاكم — نقطة الفصل الجوهرية: «المُقترح يبحث، والحاكم يحكم».

الطبقة الشكلية لنكس-كور (إعادة هندسة عكسية من البنية المرجعية
AlphaProof/Lean/TLA+/Dafny/CodeQL إلى ما تستطيعه نواة stdlib بصدق):

العقد الوحيد غير القابل للتفاوض هنا: **لا قبول إلا بحكم حاكم شكلي**.
المقترِح (LLM أو خوارزمية أو إنسان) يبحث ويقترح؛ الحاكم (فاحص النماذج،
فاحص العقود، فاحص الاستدعاءات) وحده يصدر قبولاً أو رفضاً أو
«تعذّر التحقق». الحاكم:
  * حتمي — الإدخال نفسه يعطي الحكم نفسه دائماً؛
  * نقي — لا يقرأ حالة عالمية ولا شبكة ولا ملفات؛
  * صامت لا يُفرَّغ — «تعذّر التحقق» ليس قبولاً ولو كان مريحاً.

الخرائط المرجعية الكاملة مع الحدود الصادقة: ``docs/FORMAL_REFERENCE.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum


class FormalError(Exception):
    """أساس أخطاء الطبقة الشكلية — دائماً صاخبة، لا ابتلاع."""


class FormalRejection(FormalError):
    """رفض حاكم شكلي — يحمل الدليل (مثالاً مضاداً أو سبباً)."""


class VerdictKind(Enum):
    """الحكم الثلاثي — الثالث ليس «ربما»: هو «تعذّر التحقق» صراحة."""

    ACCEPT = "accept"
    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Verdict:
    """حكم حاكم شكلي على ادعاء واحد.

    ``counterexample`` اختياري: للرفض، مثال مضاد ملموس (مدخل، مسار
    حالات، إدخال عقد)؛ لـUNKNOWN، وصف ما منع التحقق (ميزانية، مجال
    فارغ، مورد غائب). ``judge`` اسم الحاكم الفعلي — لا حكم بلا حاكم.
    """

    kind: VerdictKind
    claim: str
    reason: str
    judge: str
    counterexample: Hashable | None = None
    evidence: dict[str, float | int | str | bool | None] = field(
        default_factory=dict
    )

    @property
    def accepted(self) -> bool:
        return self.kind is VerdictKind.ACCEPT

    @property
    def rejected(self) -> bool:
        return self.kind is VerdictKind.REJECT

    def raise_if_rejected(self) -> None:
        """ارفع ``FormalRejection`` مع الدليل إن كان الحكم رفضاً."""
        if self.kind is VerdictKind.REJECT:
            suffix = (
                f" (counterexample: {self.counterexample!r})"
                if self.counterexample is not None
                else ""
            )
            raise FormalRejection(
                f"[{self.judge}] rejected: {self.claim} — {self.reason}{suffix}"
            )

    def require_accept(self) -> None:
        """العقد الصارم: لا شيء يتابع بعد هذه الدعوة إلا بحكم قبول."""
        if self.kind is not VerdictKind.ACCEPT:
            suffix = (
                f", counterexample={self.counterexample!r}"
                if self.counterexample is not None
                else ""
            )
            raise FormalRejection(
                f"[{self.judge}] did not accept: {self.claim} — "
                f"kind={self.kind.value}, reason={self.reason}{suffix}"
            )


class Judge:
    """البروتوكول القاعدي لأي حاكم شكلي.

    العقد: ``verify`` حتمي ونقي؛ يعيد ``Verdict`` ولا يرفع إلا أخطاء
    بنية (فشل بناء الحاكم نفسه، وليس رفضاً). يُرفض الادعاء؛ ما لا
    يُقدَر التحقق منه يصير UNKNOWN بسبب مكتوب — لا يصير قبولاً أبداً.
    """

    name: str = "judge"

    def verify(self, claim: str, candidate: Hashable) -> Verdict:  # pragma: no cover
        raise NotImplementedError

    def judge(self, claim: str, candidate: Hashable) -> Verdict:
        """الاسم المستقر للعقد — نفس ``verify`` دون تجاوزات."""
        return self.verify(claim, candidate)


@dataclass(frozen=True)
class PredicateJudge(Judge):
    """أبسط حاكم صادق: مسند شكلي صريح على المرشح.

    يخدم البدائيات: أي دالة حتمية ``(candidate) -> bool`` تتحول إلى
    حاكم. الرفض يحمل المرشح نفسه كدليل. ``unknown_message`` للإدخال
    غير القابل للتقييم (مثلاً دالة رفعت استثناءً — رفض بناء لا قبول).
    """

    predicate: Callable[[Hashable], bool]
    claim: str = "candidate satisfies predicate"
    name: str = "predicate-judge"
    unknown_message: str = "predicate could not evaluate the candidate"

    def verify(self, claim: str, candidate: Hashable) -> Verdict:
        """قيّم المسند على المرشح — فشل التقييم UNKNOWN لا قبول."""
        del claim  # الادعاء المعلن في المصنف هو المعتمد — لا ادعاءين
        try:
            outcome = bool(self.predicate(candidate))
        except Exception as exc:  # noqa: BLE001 — فشل التقييم ليس رفضاً ولا قبولاً
            return Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=self.claim,
                reason=f"{self.unknown_message}: {exc!r}",
                judge=self.name,
            )
        if outcome:
            return Verdict(
                kind=VerdictKind.ACCEPT,
                claim=self.claim,
                reason="predicate held",
                judge=self.name,
            )
        return Verdict(
            kind=VerdictKind.REJECT,
            claim=self.claim,
            reason="predicate failed",
            judge=self.name,
            counterexample=candidate,
        )


def all_accept(verdicts: Iterable[Verdict]) -> Verdict:
    """ركّب أحكاماً متعددة: قبول فقط إن قبل الجميع، وإلا أول رفض.

    الرفض الأول يُمرَّر كما هو (باسم حاكمه ودليله)؛ أي UNKNOWN بين
    أحكامٍ مقبولة يفسد الكل — «تعذّر التحقق» معدٍ، لا يُهمَّل.
    """
    seen: list[Verdict] = list(verdicts)
    if not seen:
        return Verdict(
            kind=VerdictKind.UNKNOWN,
            claim="composition of zero verdicts",
            reason="no judge produced a verdict — cannot certify anything",
            judge="all_accept",
        )
    for verdict in seen:
        if verdict.kind is VerdictKind.REJECT:
            return verdict
    for verdict in seen:
        if verdict.kind is VerdictKind.UNKNOWN:
            return verdict
    return Verdict(
        kind=VerdictKind.ACCEPT,
        claim="; ".join(v.claim for v in seen),
        reason=f"{len(seen)} judge(s) accepted",
        judge="all_accept(" + ",".join(v.judge for v in seen) + ")",
    )


def evidence_lines(verdicts: Sequence[Verdict]) -> tuple[str, ...]:
    """أسطر دليل جاهزة للتقرير — من الأحكام لا من الحلم."""
    lines: list[str] = []
    for v in verdicts:
        line = f"[{v.judge}] {v.kind.value}: {v.claim} — {v.reason}"
        if v.counterexample is not None:
            line += f" | counterexample: {v.counterexample!r}"
        lines.append(line)
    return tuple(lines)


__all__ = [
    "FormalError",
    "FormalRejection",
    "Judge",
    "PredicateJudge",
    "Verdict",
    "VerdictKind",
    "all_accept",
    "evidence_lines",
]
