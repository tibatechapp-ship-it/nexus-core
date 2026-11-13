"""حلقة الإثبات الوكيلية — المكافئ الصادق لحلقة AlphaProof Nexus.

إعادة هندسة عكسية لأدوار الأربعة المرجعية (Generator / Verifier /
Repairer / Terminator) تحت العقد الوحيد غير القابل للتفاوض:

  **المقترِح يبحث، والحاكم يحكم.**

  * ``Generator`` (المولّد): أي مُطلق — LLM أو خوارزمية بسيطة أو
    قائمة إصلاحات مرتبة. لا يحكم شيئاً أبداً؛ مخرجه «مرشح».
  * ``Verifier``: هو الحاكم الشكلي نفسه (``Judge`` من ``judge.py``)
    — حتمي نقي، حكمهACCEPT/REJECT/UNKNOWN لا يُناقش.
  * ``Repairer`` (المصلح): يستقبل المرشح المرفوض **وحكمه بأدلته**
    (المثال المضاد) ويقترح المرشح التالي — إصلاح موجّه بالدليل،
    لا إعادة عشوائية (عقد AxDafny/SKILLFORGE).
  * ``Terminator`` (المنهي): ميزانية صارمة معلنة — محاولات أو
    زمن. نفاد الميزانية = ``UNKNOWN`` سببه مكتوب، لا قبول مريح.

الحلقة حتمية افتراضياً (بلا LLM): نفس المدخلات تعطي نفس التقرير —
قابل للعكس في الاختبارات، وقابل للتركيب مع أي واجهة LLM لاحقاً.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field

from src.formal.judge import Judge, Verdict, VerdictKind

DEFAULT_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Attempt:
    """محاولة واحدة في الحلقة: مرشح + حكمه + دور المولّد."""

    number: int
    generator: str
    candidate: Hashable
    verdict: Verdict


@dataclass(frozen=True)
class LoopReport:
    """تقرير الحلقة: الحكم النهائي + سجل المحاولات الكامل (لا يُختصر)."""

    claim: str
    verdict: Verdict
    attempts: tuple[Attempt, ...] = ()
    stopped_because: str = "accepted"

    @property
    def accepted(self) -> bool:
        return self.verdict.kind is VerdictKind.ACCEPT

    def evidence_lines(self) -> tuple[str, ...]:
        lines: list[str] = []
        for attempt in self.attempts:
            ce = attempt.verdict.counterexample
            lines.append(
                f"#{attempt.number} [{attempt.generator}] "
                f"{attempt.verdict.kind.value}: {attempt.verdict.reason}"
                + (f" | counterexample: {ce!r}" if ce is not None else "")
            )
        return tuple(lines)


class Generator:
    """بروتوكول المولّد — يقترح ولا يحكم.

    ``propose`` يستقبل سجل المحاولات السابقة (أحكامها وأدلتها) ويعيد
    المرشح التالي؛ ``None`` يعني «استنفدت ما عندي» — الحلقة تنتهي
    UNKNOWN لا بقبول مريح.
    """

    name: str = "generator"

    def propose(
        self, claim: str, history: Sequence[Attempt]
    ) -> Hashable | None:  # pragma: no cover
        raise NotImplementedError


@dataclass(frozen=True)
class StaticGenerator(Generator):
    """مولّد قائمة ثابتة — للعروض والاختبارات وأبسط الحالات."""

    candidates: tuple[Hashable, ...]
    name: str = "static"

    def propose(
        self, claim: str, history: Sequence[Attempt]
    ) -> Hashable | None:
        del claim  # قائمة ثابتة لا تتعلم — الترتيب فقط هو ما يهم
        index = len(history)
        if index < len(self.candidates):
            return self.candidates[index]
        return None


@dataclass(frozen=True)
class CounterexampleGuidedGenerator(Generator):
    """المصلح الموجّه بالدليل — عقد الإصلاح الحقيقي.

    ``repair`` تُستدعى فقط بعد رفض: تستقبل المرشح الفاشل وحكمه، وتعيد
    مرشحاً جديداً أو ``None``. بلا استجابة صالحة تنهى الحلقة UNKNOWN.
    """

    initial: Hashable
    repair: Callable[[Hashable, Verdict], Hashable | None]
    name: str = "counterexample-guided"

    def propose(
        self, claim: str, history: Sequence[Attempt]
    ) -> Hashable | None:
        del claim
        if not history:
            return self.initial
        last = history[-1]
        if last.verdict.kind is VerdictKind.ACCEPT:
            return None
        return self.repair(last.candidate, last.verdict)


def run_prover_loop(
    claim: str,
    judge: Judge,
    generator: Generator,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> LoopReport:
    """شغّل الحلقة: اقترح ← حاكم ← أصلح بالدليل ← أنهِ بالميزانية.

    العقد: الحاكم وحده يقبل؛ كل محاولة تُسجَّل كما هي (لا اختيار
    انتقائي للسجل)؛ نفاد الميزانية أو استنفاد المولّد = UNKNOWN
    بسبب مكتوب — لا يُصنع قبول من الوضع الراهن.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive — zero attempts verify nothing")
    history: list[Attempt] = []
    stopped = "accepted"
    for number in range(1, max_attempts + 1):
        try:
            candidate = generator.propose(claim, tuple(history))
        except Exception as exc:  # noqa: BLE001 — فشل المولّد ليس قبولاً
            stopped = f"generator raised: {exc!r}"
            return LoopReport(
                claim=claim,
                verdict=Verdict(
                    kind=VerdictKind.UNKNOWN,
                    claim=claim,
                    reason=stopped,
                    judge=judge.name,
                ),
                attempts=tuple(history),
                stopped_because=stopped,
            )
        if candidate is None:
            stopped = (
                "generator exhausted after "
                f"{len(history)} attempt(s) — no candidate left to verify"
            )
            break
        verdict = judge.judge(claim, candidate)
        history.append(
            Attempt(
                number=number, generator=generator.name,
                candidate=candidate, verdict=verdict,
            )
        )
        if verdict.kind is VerdictKind.ACCEPT:
            return LoopReport(
                claim=claim,
                verdict=verdict,
                attempts=tuple(history),
                stopped_because=stopped,
            )
        if verdict.kind is VerdictKind.UNKNOWN:
            stopped = "judge could not verify — no basis to continue"
            break
    else:
        stopped = (
            f"attempt budget exhausted ({max_attempts}) — "
            "no accepted candidate"
        )
    return LoopReport(
        claim=claim,
        verdict=Verdict(
            kind=VerdictKind.UNKNOWN,
            claim=claim,
            reason=stopped,
            judge=judge.name,
        ),
        attempts=tuple(history),
        stopped_because=stopped,
    )


def loop_verdict_or_raise(report: LoopReport) -> Verdict:
    """بوبّة البوابة: ترفع صاخباً إن لم يكن الحكم النهائي قبولاً."""
    report.verdict.require_accept()
    return report.verdict


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "Attempt",
    "CounterexampleGuidedGenerator",
    "Generator",
    "LoopReport",
    "StaticGenerator",
    "loop_verdict_or_raise",
    "run_prover_loop",
]
