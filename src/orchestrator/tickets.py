"""خط التذاكر — من تذكرة مهام إلى فرع منفَّذ ومُبلَّغ.

المسار حتمي كله ولا يفاجأ:

1. **تذكرة** — هدف + معايير قبول قابلة للفحص (لا معايير غامضة).
2. **فرع** — اسم مقيَّد آمن من العنوان (لا مراوغة ولا محارف خطرة).
3. **تنفيذ** — عبر محرك مُمرَّر (محرك الكود الحقيقي أو محاكي الاختبار)؛
   بلا محرك تكون الحالة ``blocked`` معلنة لا مسمّاة.
4. **فحص** — كل معيار قبول يُفحص فردياً؛ فشل معيار واحد يمنع الإتمام.
5. **تقرير** — Markdown حتمي يُكتب في مجلد التقارير + حدث تتبع صادق.

لا ينشر ولا يدفع أبداً: الفرع يبقى محلياً والتقرير يعلن الحالة — النشر
قرار إنسان يأتي بعد التقرير لا قبله.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.observability.trace import trace_event

__all__ = [
    "STATUSES", "PRIORITIES", "Ticket", "TicketResult", "TicketEngine",
    "branch_for", "TicketRunner", "MAX_BRANCH_LENGTH",
]

#: حالات التذكرة المعلنة — لا رابع: منفَّذة / محجوبة / مرفوضة الشكل.
STATUSES: tuple[str, ...] = ("done", "blocked", "rejected")

#: أسبقيات معلنة — ترتيبها ثابت في التقارير.
PRIORITIES: tuple[str, ...] = ("low", "normal", "high")

#: حد طول اسم الفرع — تقليم بعد التنظيف لا قبله.
MAX_BRANCH_LENGTH = 60

#: نمط معرف التذكرة — حروف علوية وأرقام وشرطة: ``NT-101``.
_TICKET_ID = re.compile(r"^[A-Z][A-Z0-9]{1,11}-\d{1,6}$")


class TicketEngine(Protocol):
    """أدنى عقد محرك يُقبَل في الخط: تخطيط وفحص قبول."""

    def plan(self, goal: str) -> list[str]: ...

    def check(self, criterion: str, plan: list[str]) -> bool: ...


@dataclass(frozen=True)
class Ticket:
    """تذكرة واحدة: هوية صريحة وهدف ومعايير لا تقبل الغموض."""

    id: str
    title: str
    goal: str
    acceptance: tuple[str, ...]
    priority: str = "normal"
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _TICKET_ID.match(self.id):
            raise ValueError(f"معرف تذكرة غير صالح: {self.id} (النمط: NT-101)")
        if not self.title.strip():
            raise ValueError("عنوان التذكرة فارغ")
        if not self.goal.strip():
            raise ValueError("هدف التذكرة فارغ")
        if not self.acceptance:
            raise ValueError("لا معايير قبول — تذكرة بلا فحص لا تُقبل في الخط")
        if self.priority not in PRIORITIES:
            raise ValueError(f"أسبقية غير معروفة: {self.priority} (المعروفة: {PRIORITIES})")


@dataclass(frozen=True)
class TicketResult:
    """مخرجات الخط: الحالة والفرع والتقرير وفحوص المعايير ومدة التنفيذ."""

    status: str
    branch: str
    ticket_id: str
    report_path: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    plan: tuple[str, ...] = ()
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"حالة غير معروفة: {self.status} (المعروفة: {STATUSES})")


def _slug(text: str) -> str:
    """عنوان → سُقلة آمنة: لاتيني وأرقام وشرطات، والعربي يُسقَط بلا قلق."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def branch_for(ticket: Ticket) -> str:
    """اسم الفرع: ``tickets/<id>-<سُقلة>`` — مقيَّد ومنظَّف من كل خطر."""
    slug = _slug(ticket.title) or "ticket"
    branch = f"tickets/{ticket.id.lower()}-{slug}"
    branch = re.sub(r"[^a-z0-9/._-]+", "-", branch)
    if len(branch) > MAX_BRANCH_LENGTH:
        branch = branch[:MAX_BRANCH_LENGTH].rstrip("-.")
    return branch


def _plan_fallback(goal: str) -> list[str]:
    """تخطيط حتمي بديل — بلا محرك: تقطيع الهدف لخطوات مقروءة."""
    sentences = [s.strip() for s in re.split(r"[.؟!\n]+", goal) if s.strip()]
    return sentences[:6] if sentences else [goal.strip()]


class TicketRunner:
    """منفّذ الخط — محرك مُمرَّر ومجلد تقارير ثابت وتتبع صادق."""

    def __init__(
        self,
        engine: TicketEngine | None = None,
        reports_dir: Path | None = None,
        trace: bool = True,
    ) -> None:
        self.engine = engine
        self._reports_dir = Path(reports_dir) if reports_dir else None
        self._trace = trace

    def _report_path(self, ticket: Ticket) -> Path:
        root = self._reports_dir
        if root is None:
            root = Path(__file__).resolve().parents[2] / "reports" / "tickets"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"ticket-{ticket.id}.md"

    def _write_report(
        self,
        ticket: Ticket,
        result: TicketResult,
        detail: str,
    ) -> Path:
        path = self._report_path(ticket)
        status_label = {"done": "منفَّذة", "blocked": "محجوبة", "rejected": "مرفوضة الشكل"}
        lines = [
            f"# تذكرة {ticket.id} — {ticket.title}",
            "",
            f"**الحالة**: {status_label[result.status]} · **الفرع**: `{result.branch}` "
            f"· **الأسبقية**: {ticket.priority} · **المدة**: {result.duration_ms:.1f}ms",
            "",
            "## الهدف",
            "",
            ticket.goal,
            "",
        ]
        if result.plan:
            lines += ["## الخطة", ""]
            lines += [f"{i}. {step}" for i, step in enumerate(result.plan, 1)]
            lines.append("")
        lines += ["## معايير القبول", "", "| المعيار | النتيجة |", "|---|---|"]
        for criterion, passed in result.checks.items():
            lines.append(f"| {criterion} | {'ناجح' if passed else 'فاشل'} |")
        if detail:
            lines += ["", "## التفصيل", "", detail]
        lines += [
            "",
            "> الفرع محلي لا منشور — النشر قرار إنسان بعد قراءة هذا التقرير.",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def run(self, ticket: Ticket) -> TicketResult:
        """شغّل التذكرة في الخط — لا استثناء يهدم الخط؛ العطل حالة معلنة."""
        t0 = time.perf_counter()
        branch = branch_for(ticket)
        plan: list[str] = []
        checks: dict[str, bool] = {}
        status = "done"
        detail = ""

        if self.engine is None:
            status = "blocked"
            detail = "لا محرك ممرَّر — الخط لا يسمّي تنفيذاً بلا تنفيذ"
            plan = tuple(_plan_fallback(ticket.goal))  # type: ignore[assignment]
        else:
            try:
                plan = list(self.engine.plan(ticket.goal))
                for criterion in ticket.acceptance:
                    checks[criterion] = bool(self.engine.check(criterion, plan))
                if not all(checks.values()):
                    status = "blocked"
                    failed = [c for c, ok in checks.items() if not ok]
                    detail = "معايير فاشلة: " + "؛ ".join(failed)
            except Exception as exc:  # noqa: BLE001 — عطل المحرك حالة معلنة
                status = "blocked"
                detail = f"المحرك رفع {type(exc).__name__}: {exc}"
                checks = {}

        duration_ms = (time.perf_counter() - t0) * 1000.0
        result = TicketResult(
            status=status,
            branch=branch,
            ticket_id=ticket.id,
            checks=checks,
            plan=tuple(plan),
            duration_ms=duration_ms,
        )
        report_path = self._write_report(ticket, result, detail)
        result = TicketResult(
            status=result.status,
            branch=result.branch,
            ticket_id=result.ticket_id,
            report_path=str(report_path),
            checks=result.checks,
            plan=result.plan,
            duration_ms=result.duration_ms,
        )
        if self._trace:
            trace_event(
                "ticket-runner", "run",
                outcome=result.status,
                duration_ms=duration_ms,
                ticket=ticket.id,
                branch=branch,
                failed=str(sum(1 for ok in checks.values() if not ok)),
            )
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ticket", description="خط التذاكر — من تذكرة إلى فرع مُبلَّغ")
    parser.add_argument("--id", required=True, help="معرف التذكرة NT-101")
    parser.add_argument("--title", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--acceptance", action="append", required=True,
                        help="معيار قبول (كرر الخيار لكل معيار)")
    parser.add_argument("--priority", choices=PRIORITIES, default="normal")
    parser.add_argument("--reports-dir", default=None)
    args = parser.parse_args(argv)
    try:
        ticket = Ticket(
            id=args.id, title=args.title, goal=args.goal,
            acceptance=tuple(args.acceptance), priority=args.priority,
        )
    except ValueError as exc:
        print(f"rejected: {exc}")
        return 2
    runner = TicketRunner(
        reports_dir=Path(args.reports_dir) if args.reports_dir else None)
    result = runner.run(ticket)
    print(f"{result.status} {result.branch} {result.report_path}")
    return 0 if result.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
