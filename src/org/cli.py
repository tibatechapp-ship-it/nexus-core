"""واجهة سطر أوامر التنظيم — تشغيل وعرض كل شيء بلا خادم ولا شبكة.

الأوامر المعلنة:

* ``mission``      — إنشاء مهمة وتشغيلها كاملة (A→G) وطباعة الخلاصة.
* ``show``         — عرض مهمة مخزنة بتفاصيلها وأدلتها.
* ``dashboard``    — لقطة اللوحة والتقرير الحتمي.
* ``lessons``      — الدروس النشطة والأنماط المتكررة.
* ``metrics``      — لقطة المقاييس الكاملة.
* ``approve``      — تسجيل قرار موافقة بشرية على طلب قائم.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.org.contracts import Mission
from src.org.dashboard import OrgDashboard
from src.org.learning import LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.pipeline import MissionPipeline
from src.org.store import OrgStore
from src.ops.store import OpsStore

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """مُحلّل الأوامر — كل أمر بوصف معلن."""
    p = argparse.ArgumentParser(
        prog="org",
        description="التنظيم الهندسي الذاتي — تشغيل وعرض وقرار.")
    p.add_argument("--db", default="data/org.db", help="مسار قاعدة التنظيم")
    p.add_argument("--ops-db", default="data/ops.db",
                   help="مسار قاعدة الطبقة التشغيلية")
    p.add_argument("--outdir", default="reports/org", help="مجلد التقارير")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mission", help="إنشاء مهمة وتشغيلها A→G")
    m.add_argument("--title", required=True)
    m.add_argument("--objective", required=True)
    m.add_argument("--repo", default="")
    m.add_argument("--max-output-tokens", type=int, default=None,
                   help="سقف توكنات الخرج للمهمة (اختياري، موجب)")

    s = sub.add_parser("show", help="عرض مهمة مخزنة")
    s.add_argument("mission_id")

    sub.add_parser("dashboard", help="لقطة اللوحة والتقرير")

    sub.add_parser("lessons", help="الدروس والأنماط")

    sub.add_parser("metrics", help="لقطة المقاييس")

    a = sub.add_parser("approve", help="قرار موافقة بشرية")
    a.add_argument("approval_id")
    a.add_argument("--yes", action="store_true", help="موافقة (رفض غيابه)")
    a.add_argument("--by", required=True, help="اسم صانع القرار")
    return p


def _stores(args: argparse.Namespace) -> tuple[OrgStore, OpsStore]:
    org = OrgStore(args.db)
    ops = OpsStore(args.ops_db)
    return org, ops


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _cmd_mission(args: argparse.Namespace) -> int:
    org, ops = _stores(args)
    pipeline = MissionPipeline(org, ops, outdir=args.outdir)
    report = pipeline.run(title=args.title, objective=args.objective,
                          repo_path=args.repo,
                          output_token_limit=args.max_output_tokens)
    _emit(report.to_dict())
    return 0 if report.mission.status == "done" else 1


def _cmd_show(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    mission = org.mission_get(args.mission_id)
    if mission is None:
        print(f"مهمة غير موجودة: {args.mission_id}", file=sys.stderr)
        return 2
    tasks = org.tasks_for_mission(mission.id)
    claims = org.claims_for(mission.id)
    approvals = org.approvals_for(mission.id)
    _emit({
        "mission": mission.to_dict(),
        "tasks": [{"id": t["id"], "dept": t["dept"], "state": t["state"],
                   "error": t["error"]} for t in tasks],
        "claims": [{"statement": c.statement, "status": c.status}
                   for c in claims],
        "approvals": [{"id": a.id, "kind": a.kind, "subject": a.subject,
                       "approved": a.approved, "decided_by": a.decided_by}
                      for a in approvals],
        "audit_tail": org.tail_audit(8),
    })
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    dash = OrgDashboard(org, outdir=args.outdir)
    paths = dash.write()
    _emit({"snapshot": dash.snapshot(), "files": paths})
    return 0


def _cmd_lessons(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    engine = LessonsEngine(org)
    _emit({
        "active_lessons": engine.lessons_for_planning(),
        "recurring_patterns": engine.recurring_patterns(),
    })
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    _emit(OrgMetrics(org).snapshot())
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    approval = org.decide_approval(args.approval_id, approved=args.yes,
                                   decided_by=args.by)
    _emit({"id": approval.id, "approved": approval.approved,
           "decided_by": approval.decided_by,
           "decided_at": approval.decided_at})
    return 0


def main(argv: list[str] | None = None) -> int:
    """نقطة الدخول — توجيه مباشر لأوامر معلنة."""
    args = build_parser().parse_args(argv)
    handlers = {
        "mission": _cmd_mission, "show": _cmd_show,
        "dashboard": _cmd_dashboard, "lessons": _cmd_lessons,
        "metrics": _cmd_metrics, "approve": _cmd_approve,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
