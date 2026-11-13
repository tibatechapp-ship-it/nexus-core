"""فاحص العقود — المكافئ الصادق لمستوى Dafny.

إعادة هندسة عكسية: جوهر Dafny هو «المواصفة حول الكود ثم إثباتها لكل
المدخلات». بلا SMT، المكافئ الصادق داخل نواة stdlib هو **الإثبات
بالسرد المحدود** (bounded exhaustive) على مجال مُعلن:

  * ``requires`` — شروط مسبقة تحدد مجال المدخلات المعنيّ؛ المدخل
    الذي يخلف شرطاً مسبقاً **خارج العقد** (يُتخطى، لا يُحاكم).
  * ``ensures`` — شروط لاحقة على الناتج؛ أي مخالفة = رفض بأول
    مثال مضاد كامل (المدخل + الناتج).
  * مجال فارغ (لا مدخل يحقق الشروط المسبقة) = ``UNKNOWN`` سببه
    «مواصفة غائبة المعنى» — لا قبول فارغ. هذا عقد SKILLFORGE
    الأدق: المواصفة العاقرة لا تُشهّد نجاحاً.
  * ميزانية ``max_cases`` معلنة: المجال الأكبر من الميزانية →
    UNKNOWN بالسبب (نظام عينات لا يقدّم يقيناً؛ الأمانة قبل الطموح).

يُضاف هذا على ``src.verify`` (التحقق بالتنفيذ): هنا العقود تُحاكم
بلا تنفيذ أي كود أجنبي — دوال نقية ومجالات صريحة فقط.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from src.formal.judge import Verdict, VerdictKind

Inputs = tuple  # عادة tuple من القيم؛ أي Hashable مقبول
Predicate = Callable[..., bool]


@dataclass(frozen=True)
class Contract:
    """عقد دالة: شروط مسبقة ولاحقة — كلها مسندات حتمية نقيّة.

    ``requires`` تُستدعى بفك المدخل ``(args...)``؛ ``ensures`` تُستدعى
    ``(*args, result)`` — الناتج آخر وسيط دائماً.
    """

    name: str
    requires: tuple[Predicate, ...] = ()
    ensures: tuple[Predicate, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not self.ensures:
            raise ValueError(
                f"contract {self.name!r}: no ensures clauses — a contract "
                "that promises nothing cannot be verified or violated"
            )


@dataclass(frozen=True)
class InputSpace:
    """مجال مدخلات مُعلن: قابل للسرد بالكامل أو مولّد بعينة محدودة.

    ``exhaustive`` يُسردها جميعاً؛ ``sampled`` يعني أنها عينة تقديرية
    (تُصرّح في التقرير كعينة، لا كإثبات) — كلاهما مقبول، والتمييز
    إلزامي في النتيجة.
    """

    candidates: Iterable[Inputs]
    sampled: bool = False
    label: str = "input-space"

    def materialise(self, max_cases: int) -> tuple[tuple[Inputs, ...], bool]:
        """اجمع حتى ``max_cases`` مدخلاً؛ يعيد (القائمة، هل اقتُطع؟)."""
        collected: list[Inputs] = []
        truncated = False
        for candidate in self.candidates:
            if len(collected) >= max_cases:
                truncated = True
                break
            collected.append(candidate)
        return tuple(collected), truncated


@dataclass(frozen=True)
class ContractReport:
    """تقرير فحص عقد: الحكم + الدليل."""

    contract: str
    verdict: Verdict
    domain_cases: int = 0
    evaluated_cases: int = 0
    skipped_out_of_domain: int = 0
    sampled: bool = False
    failing_input: Inputs | None = None
    failing_result: object = None
    violated_ensures: tuple[str, ...] = field(default_factory=tuple)


def check_contract(
    function: Callable[..., object],
    contract: Contract,
    space: InputSpace,
    max_cases: int = 2_000,
) -> ContractReport:
    """حاكم العقود: أسرد المجال، أفلتر بالشروط المسبقة، أحاكم اللاحقة.

    العقد الحاكم (مرتبة، لا تفاوض):
      1. مجال مقتطع بالميزانية → ``UNKNOWN`` (عينة ليست يقيناً).
      2. مجال فارغ بعد الفلترة → ``UNKNOWN`` (مواصفة عاقرة).
      3. أول مخالفة لاحقة → ``REJECT`` بمثال مضاد كامل.
      4. كل الحالات مرّت → ``ACCEPT`` — وبوضوح: إن كانت العينة
         تقديرية فالحكم يقول «bounded-sampled» لا «exhaustive».
    """
    if space.sampled and len(contract.ensures) > 0:
        # العينة التقديرية مسموحة لكنها لا تُقدَّم كإثبات سرد كامل —
        # التقرير يصرّح بالفرق (لا يغيّر الحكم؛ الوضوح هو العقد).
        pass

    candidates, truncated = space.materialise(max_cases)
    evaluated = 0
    skipped = 0
    for args in candidates:
        try:
            in_domain = all(pred(*args) for pred in contract.requires)
        except Exception as exc:  # noqa: BLE001 — شرط مسبق رفع استثناءً
            return ContractReport(
                contract=contract.name,
                verdict=Verdict(
                    kind=VerdictKind.UNKNOWN,
                    claim=f"contract {contract.name!r} holds on its domain",
                    reason=f"requires predicate raised on {args!r}: {exc!r}",
                    judge="contract-checker",
                ),
                domain_cases=len(candidates),
                evaluated_cases=evaluated,
                skipped_out_of_domain=skipped,
                sampled=space.sampled,
            )
        if not in_domain:
            skipped += 1
            continue
        try:
            result = function(*args)
        except Exception as exc:  # noqa: BLE001 — الدالة رفضت المدخل
            return ContractReport(
                contract=contract.name,
                verdict=Verdict(
                    kind=VerdictKind.REJECT,
                    claim=f"contract {contract.name!r} holds on its domain",
                    reason=(
                        f"function raised {exc!r} on in-domain input "
                        f"{args!r} — a contract violation unless declared"
                    ),
                    judge="contract-checker",
                    counterexample=(args, None),
                ),
                domain_cases=len(candidates),
                evaluated_cases=evaluated,
                skipped_out_of_domain=skipped,
                sampled=space.sampled,
                failing_input=args,
            )
        evaluated += 1
        for ensure in contract.ensures:
            try:
                holds = bool(ensure(*args, result))
            except Exception as exc:  # noqa: BLE001
                return ContractReport(
                    contract=contract.name,
                    verdict=Verdict(
                        kind=VerdictKind.UNKNOWN,
                        claim=f"contract {contract.name!r} holds on its domain",
                        reason=f"ensures predicate raised on {args!r}: {exc!r}",
                        judge="contract-checker",
                    ),
                    domain_cases=len(candidates),
                    evaluated_cases=evaluated,
                    skipped_out_of_domain=skipped,
                    sampled=space.sampled,
                )
            if not holds:
                return ContractReport(
                    contract=contract.name,
                    verdict=Verdict(
                        kind=VerdictKind.REJECT,
                        claim=f"contract {contract.name!r} holds on its domain",
                        reason=f"ensures clause violated on input {args!r}",
                        judge="contract-checker",
                        counterexample=(args, result),
                    ),
                    domain_cases=len(candidates),
                    evaluated_cases=evaluated,
                    skipped_out_of_domain=skipped,
                    sampled=space.sampled,
                    failing_input=args,
                    failing_result=result,
                )

    if truncated:
        return ContractReport(
            contract=contract.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"contract {contract.name!r} holds on its domain",
                reason=(
                    f"input space truncated at max_cases={max_cases} — "
                    "a sample never certifies exhaustiveness"
                ),
                judge="contract-checker",
                evidence={"domain_cases": len(candidates)},
            ),
            domain_cases=len(candidates),
            evaluated_cases=evaluated,
            skipped_out_of_domain=skipped,
            sampled=space.sampled,
        )
    if evaluated == 0:
        return ContractReport(
            contract=contract.name,
            verdict=Verdict(
                kind=VerdictKind.UNKNOWN,
                claim=f"contract {contract.name!r} holds on its domain",
                reason=(
                    f"vacuous specification: {skipped} candidate(s) all out "
                    "of domain — nothing was actually verified"
                ),
                judge="contract-checker",
                evidence={"domain_cases": len(candidates)},
            ),
            domain_cases=len(candidates),
            evaluated_cases=0,
            skipped_out_of_domain=skipped,
            sampled=space.sampled,
        )
    mode = "bounded-sampled" if space.sampled else "bounded-exhaustive"
    return ContractReport(
        contract=contract.name,
        verdict=Verdict(
            kind=VerdictKind.ACCEPT,
            claim=f"contract {contract.name!r} holds on its domain",
            reason=(
                f"{evaluated} in-domain case(s) passed ({mode}); "
                f"{skipped} out-of-domain skipped"
            ),
            judge="contract-checker",
            evidence={"evaluated": evaluated, "mode": mode},
        ),
        domain_cases=len(candidates),
        evaluated_cases=evaluated,
        skipped_out_of_domain=skipped,
        sampled=space.sampled,
    )


def ensure(*, clause: Predicate) -> Predicate:
    """مُنشئ صغير لتنسيق شروط اللاحقة — توثيقاً لا قوة جديدة."""
    return clause


def requires(*, clause: Predicate) -> Predicate:
    """مُنشئ صغير لتنسيق الشروط المسبقة — توثيقاً لا قوة جديدة."""
    return clause


__all__ = [
    "Contract",
    "ContractReport",
    "Inputs",
    "InputSpace",
    "check_contract",
    "ensure",
    "requires",
]
