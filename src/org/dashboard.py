"""لوحة التنظيم — لقطة عدّية وتقرير حتمي بنفس أسلوب لوحة العمليات.

القواعد المعلنة:

* **الحتمية**: نفس المخزن يعطي نفس نص التقرير حرفيًا — لا طوابع زمنية
  في المتن، والترتيب ثابت، والأعداد من استعلامات ثابتة. هذا يجعل
  التقرير قابلًا للاختبار بالمقارنة النصية المباشرة.
* **اللوحة تقرأ ولا تعرف**: لا كتابة في المتجر من اللوحة — عرض فقط
  لأعداد المهمة والأطوار والبوابات والمقاييس والدروس.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.org.learning import LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.store import OrgStore

__all__ = ["OrgDashboard"]

#: ترتيب الأطوار في العرض — ثابت معلن لا ترتيب استعلامي متقلب.
PHASE_ORDER: tuple[str, ...] = (
    "A_REQUIREMENTS", "B_INTEL", "C_DEVELOP", "D_REVIEW",
    "E_TESTING", "F_VERIFICATION", "G_RELEASE", "FAILED", "CANCELLED",
)


class OrgDashboard:
    """لوحة التنظيم — لقطة، تقرير حتمي، كتابة ملفات."""

    def __init__(self, store: OrgStore,
                 outdir: str | Path = "reports/org") -> None:
        self.store = store
        self.metrics = OrgMetrics(store)
        self.lessons = LessonsEngine(store)
        self.outdir = Path(outdir)

    # ── اللقطة العدّية ────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """لقطة كاملة — مهام بالأطوار، بوابات، مقاييس، دروس."""
        missions = self.store.mission_list()
        by_phase: dict[str, int] = {p: 0 for p in PHASE_ORDER}
        by_status: dict[str, int] = {}
        for m in missions:
            by_phase[m.phase] = by_phase.get(m.phase, 0) + 1
            by_status[m.status] = by_status.get(m.status, 0) + 1
        counts = self.store.counts()
        return {
            "missions_total": len(missions),
            "missions_by_phase": {p: n for p, n in by_phase.items() if n},
            "missions_by_status": dict(sorted(by_status.items())),
            "tasks": counts.get("tasks", 0),
            "agent_runs": counts.get("agent_runs", 0),
            "reviews": counts.get("reviews", 0),
            "findings": counts.get("findings", 0),
            "claims": counts.get("claims", 0),
            "evidence": counts.get("evidence", 0),
            "approvals": counts.get("approvals", 0),
            "lessons": counts.get("lessons", 0),
            "metrics_rates": {
                "completion_rate": self.metrics.completion_rate(),
                "verified_fix_rate": self.metrics.verified_fix_rate(),
                "false_positive_rate": self.metrics.false_positive_rate(),
                "regression_rate": self.metrics.regression_rate(),
                "agent_failure_rate": self.metrics.agent_failure_rate(),
            },
            "usage": self.metrics.usage_totals(),
            "recurring_patterns": self.lessons.recurring_patterns(),
        }

    # ── التقرير الحتمي ────────────────────────────────────────────────────

    def markdown_report(self) -> str:
        """تقرير Markdown حتمي — نفس الحالة نفس النص حرفيًا."""
        snap = self.snapshot()
        lines = ["# لوحة التنظيم الهندسي الذاتي", ""]
        lines.append(f"- المهام: {snap['missions_total']}")
        phases = " · ".join(
            f"{p}:{n}" for p, n in sorted(snap["missions_by_phase"].items()))
        lines.append(f"- الأطوار: {phases or 'لا مهام'}")
        statuses = " · ".join(
            f"{s}:{n}" for s, n in snap["missions_by_status"].items())
        lines.append(f"- الحالات: {statuses or 'لا مهام'}")
        lines += ["", "## العدّادات"]
        for key in ("tasks", "agent_runs", "reviews", "findings", "claims",
                    "evidence", "approvals", "lessons"):
            lines.append(f"- {key}: {snap[key]}")
        lines += ["", "## المعدلات"]
        rates = snap["metrics_rates"]
        for name in sorted(rates):
            lines.append(f"- {name}: {rates[name]}")
        usage = snap["usage"]
        lines += [
            "",
            "## الاستهلاك",
            f"- توكنات داخلة: {usage['tokens_in']} · خارجة: "
            f"{usage['tokens_out']}",
            f"- كلفة تقديرية: {usage['cost_usd']}$ · متوسط زمن استدعاء: "
            f"{usage['avg_latency_ms']}ms",
        ]
        patterns = snap["recurring_patterns"]
        lines += ["", "## الأنماط المتكررة"]
        if patterns:
            lines += [f"- {p['category']}: {p['count']} مرة" for p in patterns]
        else:
            lines.append("- لا أنماط متكررة فوق العتبة.")
        lines += ["", "## الدروس النشطة"]
        active = self.lessons.lessons_for_planning()
        if active:
            lines += [f"- {t}" for t in active[:10]]
        else:
            lines.append("- لا دروس نشطة بعد.")
        return "\n".join(lines) + "\n"

    # ── الكتابة ───────────────────────────────────────────────────────────

    def write(self, subdir: str = "") -> dict[str, str]:
        """كتابة اللقطة والتقرير — JSON وMarkdown على القرص."""
        target = self.outdir / subdir if subdir else self.outdir
        target.mkdir(parents=True, exist_ok=True)
        snap_path = target / "org_dashboard.json"
        snap_path.write_text(
            __import__("json").dumps(self.snapshot(), sort_keys=True,
                                     ensure_ascii=False, indent=2),
            encoding="utf-8")
        report_path = target / "org_dashboard.md"
        report_path.write_text(self.markdown_report(), encoding="utf-8")
        return {"snapshot": str(snap_path), "report": str(report_path)}
