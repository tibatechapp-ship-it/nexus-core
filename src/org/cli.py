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

from src.org.contracts import Approval, Mission
from src.org.dashboard import OrgDashboard
from src.org.learning import LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.pipeline import MissionPipeline
from src.org.store import OrgStore
from src.ops.store import OpsStore

__all__ = ["build_parser", "main"]


def _positive_output_tokens(value: str) -> int:
    """Parse a positive SQLite-safe output-token ceiling."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("يجب إدخال عدد صحيح موجب") from exc
    if parsed <= 0 or parsed > 2**63 - 1:
        raise argparse.ArgumentTypeError("السقف يجب أن يكون موجبًا وضمن حد SQLite")
    return parsed


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
    m.add_argument("--mission-id", default="",
                   help="تشغيل مهمة موجودة؛ مطلوب لمسار موافقة الحاوية")
    m.add_argument("--execution-mode", choices=("process", "container"),
                   required=True, help="وضع التشغيل الأمني الصريح")
    m.add_argument("--trust-local", action="store_true",
                   help="إقرار صريح بأن المستودع موثوق للتنفيذ المحلي")
    m.add_argument("--container-image", default="",
                   help="صورة حاوية مثبتة ببصمة sha256")
    m.add_argument("--container-enabled", action="store_true",
                   help="تفعيل تشغيل الحاوية صراحة")
    m.add_argument("--approval-id", default="",
                   help="معرّف موافقة run_untrusted المسجلة للمهمة")
    m.add_argument("--max-output-tokens", type=_positive_output_tokens, default=None,
                   help="سقف توكنات الخرج للمهمة (اختياري، موجب)")

    c = sub.add_parser("create-mission", help="إنشاء مهمة دون تشغيلها")
    c.add_argument("--title", required=True)
    c.add_argument("--objective", required=True)
    c.add_argument("--repo", default="")
    c.add_argument("--max-output-tokens", type=_positive_output_tokens, default=None)

    s = sub.add_parser("show", help="عرض مهمة مخزنة")
    s.add_argument("mission_id")

    sub.add_parser("dashboard", help="لقطة اللوحة والتقرير")

    sub.add_parser("lessons", help="الدروس والأنماط")

    sub.add_parser("metrics", help="لقطة المقاييس")

    r = sub.add_parser(
        "request-run-approval",
        help="طلب موافقة بشرية على تشغيل صورة حاوية مثبتة ببصمة sha256",
    )
    r.add_argument("mission_id")
    r.add_argument("--container-image", required=True)

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
    existing_mission = None
    if args.mission_id:
        existing_mission = org.mission_get(args.mission_id)
        if existing_mission is None:
            raise SystemExit(f"mission not found: {args.mission_id}")
        if (
            existing_mission.title != args.title
            or existing_mission.objective != args.objective
            or existing_mission.repo_path != args.repo
            or existing_mission.output_token_limit != args.max_output_tokens
        ):
            raise SystemExit("--mission-id fields must match the stored mission")
    elif args.execution_mode == "container":
        raise SystemExit(
            "container mode requires --mission-id from create-mission so approval "
            "is bound to the mission being executed"
        )
    if args.execution_mode == "process":
        if not args.trust_local:
            raise SystemExit("--execution-mode process requires --trust-local")
        policy = {
            "schema_version": 1, "execution_mode": "process",
            "trusted_local": True,
        }
    else:
        if not args.container_enabled or not args.container_image or not args.approval_id:
            raise SystemExit(
                "container mode requires --container-enabled, --container-image "
                "and --approval-id"
            )
        policy = {
            "schema_version": 1, "execution_mode": "container",
            "container_enabled": True, "container_image": args.container_image,
            "approval_id": args.approval_id,
        }
    pipeline = MissionPipeline(org, ops, outdir=args.outdir)
    report = pipeline.run(title=args.title, objective=args.objective,
                          repo_path=args.repo,
                          output_token_limit=args.max_output_tokens,
                          execution_policy=policy,
                          existing_mission=existing_mission)
    _emit(report.to_dict())
    return 0 if report.mission.status == "done" else 1


def _cmd_create_mission(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    mission = org.create_mission(Mission(
        title=args.title, objective=args.objective, repo_path=args.repo,
        output_token_limit=args.max_output_tokens,
    ))
    _emit(mission.to_dict())
    return 0


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


def _cmd_request_run_approval(args: argparse.Namespace) -> int:
    org, _ = _stores(args)
    mission = org.mission_get(args.mission_id)
    if mission is None:
        print(f"مهمة غير موجودة: {args.mission_id}", file=sys.stderr)
        return 2
    image = args.container_image
    digest = image.rsplit("@sha256:", 1)[-1] if "@sha256:" in image else ""
    if (len(digest) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in digest)):
        print("الصورة يجب أن تكون مثبتة ببصمة sha256 صحيحة", file=sys.stderr)
        return 2
    approval = org.request_approval(Approval(
        mission_id=mission.id, kind="run_untrusted", subject=image,
        note="Authorize execution only inside this immutable container image",
    ))
    _emit({
        "approval_id": approval.id, "kind": approval.kind,
        "subject": approval.subject, "approved": approval.approved,
    })
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
        "mission": _cmd_mission, "create-mission": _cmd_create_mission,
        "show": _cmd_show,
        "dashboard": _cmd_dashboard, "lessons": _cmd_lessons,
        "metrics": _cmd_metrics,
        "request-run-approval": _cmd_request_run_approval,
        "approve": _cmd_approve,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
