"""أوامر CLI للطبقة التشغيلية — نقطة دخول واحدة ``nexus ops`` للأوامر السبعة.

الأوامر:

* ``nexus ops radar``       — دورة رصد كتالوغي (بلا شبكة) أو بمُجلب حي.
* ``nexus ops index-ingest``— إدخال ملف نصي إلى الفهرس (تهذيب + تقطيع + تضمين).
* ``nexus ops index-query`` — استرجاع بميزانية توكن مع استشهادات.
* ``nexus ops sandbox``     — فحص هدف + حكم ثلاثي + تذكرة تلقائية.
* ``nexus ops tickets``     — قائمة التذاكر بحالاتها أو تذكرة واحدة.
* ``nexus ops webqa``       — بوابة فحص ويب على مجلد.
* ``nexus ops dashboard``   — اللوحة الواحدة إلى ملفات reports/ops.

كل أمر يعمل على قاعدة واحدة ``--db`` (الافتراضي ``data/ops.db``)، وكل
فشل يُطبع سطرًا صريحًا برمز خروج 1 — لا اختفاء أخطاء.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from src.ops.store import OpsStore

__all__ = ["DEFAULT_DB_PATH", "DEFAULT_REPORT_DIR", "run_ops_command"]

#: قاعدة المخزن الواحد الافتراضية — نسبية لجذر المستودع.
DEFAULT_DB_PATH = "data/ops.db"

#: مجلد تقارير اللوحة الافتراضي.
DEFAULT_REPORT_DIR = "reports/ops"


def _store(args: argparse.Namespace) -> OpsStore:
    """بناء المخزن من أمر فرعي — كل الأوامر تمر من هنا وحدها."""
    from src.ops.store import OpsStore
    return OpsStore(getattr(args, "db", DEFAULT_DB_PATH))


# ── الأوامر السبعة ────────────────────────────────────────────────────────

def _cmd_radar(args: argparse.Namespace) -> int:
    """دورة رصد — كتالوغي افتراضيًا؛ ``--live`` الخطّاف الحي المعلن."""
    from src.ops.radar import OpsRadar, http_fetch, load_config
    radar = OpsRadar(_store(args), load_config(getattr(args, "config", None)))
    result = radar.run(args.cadence, fetcher=http_fetch if args.live else None)
    payload = result.to_dict()
    print(json.dumps({
        "cadence": result.cadence,
        "sources_ok": payload["sources_ok"],
        "sources_failed": payload["sources_failed"],
        "stored": payload["items_stored"],
        "deduped": payload["items_deduped"],
        "skipped_quiet": payload["skipped_quiet"],
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_index_ingest(args: argparse.Namespace) -> int:
    """إدخال ملف إلى الفهرس — يطبع عدد الشرائح وما مُهذَّب."""
    from src.ops.indexer import OpsIndex
    index = OpsIndex(_store(args))
    result = index.ingest_file(
        args.path, doc_id=args.doc_id or Path(args.path).name,
        acl=args.acl, ttl_days=args.ttl,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_index_query(args: argparse.Namespace) -> int:
    """استرجاع بميزانية توكن — الشرائح والاستشهادات فقط."""
    from src.ops.indexer import OpsIndex
    index = OpsIndex(_store(args))
    result = index.retrieve(args.query, budget_tokens=args.budget, acl=args.acl)
    slim = {
        "tokens_used": result["tokens_used"],
        "citations": result["citations"],
        "slices": [
            {"doc_id": s["doc_id"], "title": s["title"], "tokens": s["tokens"],
             "score": s["score"], "text": s["text"][:200]}
            for s in result["slices"]
        ],
    }
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    return 0


def _cmd_sandbox(args: argparse.Namespace) -> int:
    """فحص هدف + حكم — أدلة وثقة وتذكرة تلقائية للمؤكَّد وغير المحسوم."""
    from src.ops.tickets import TicketBoard
    from src.ops.verdict import VerdictEngine
    engine = VerdictEngine(_store(args))
    requirements = None
    if args.requirements:
        requirements = Path(args.requirements).read_text(encoding="utf-8")
    verdict = engine.evaluate(
        target=args.target, target_path=args.path,
        requirements=requirements,
        probe_code=args.probe,
    )
    ticket = engine.ensure_ticket(verdict)
    print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    if ticket is not None:
        print(f"تذكرة مفتوحة: {ticket.id} ({ticket.branch})")
    return 0 if verdict.verdict != "confirmed" else 2


def _cmd_tickets(args: argparse.Namespace) -> int:
    """قائمة التذاكر — بالحالة أو الكل، أو تذكرة واحدة بمعرّفها."""
    from src.ops.store import OpsStore
    store = OpsStore(getattr(args, "db", DEFAULT_DB_PATH))
    if args.ticket_id:
        t = store.ticket_get(args.ticket_id)
        if t is None:
            print(f"تذكرة غير موجودة: {args.ticket_id}")
            return 1
        print(json.dumps(t.to_dict(), ensure_ascii=False, indent=2))
        return 0
    board_tickets = store.ticket_list(state=args.state)
    for t in board_tickets:
        publish = "نشر مفتوح" if t.publish_allowed else "نشر محجوب"
        print(f"{t.id} [{t.state}] ({t.origin}) {publish} — {t.title[:60]}")
    print(f"الإجمالي: {len(board_tickets)}")
    return 0


def _cmd_webqa(args: argparse.Namespace) -> int:
    """بوابة فحص ويب — يطبع النتائج ويعيد 1 عند فشل الحاجبة."""
    from src.ops.webqa import OpsWebQA
    gate = OpsWebQA(_store(args)).run(args.path)
    for f in gate.findings:
        print(f"- [{f['severity']}] {f['check']}: {f['message']}")
    print(f"الحكم: {'نجحت البوابة' if gate.passed else 'فشلت البوابة الحاجبة'}")
    if gate.ticket_id:
        print(f"تذكرة مفتوحة: {gate.ticket_id}")
    return 0 if gate.passed else 1


def _cmd_dashboard(args: argparse.Namespace) -> int:
    """اللوحة الواحدة — يطبع التقرير ويكتب الملفات الثابتة."""
    from src.ops.dashboard import OpsDashboard
    dashboard = OpsDashboard(_store(args), outdir=args.outdir)
    files = dashboard.write()
    print(dashboard.render_markdown())
    print(f"كُتبت: {files['markdown']} · {files['json']}")
    return 0


def _cmd_org(args: argparse.Namespace) -> int:
    """تفويض لأوامر التنظيم — org.cli يحلل وسائطه بنفس عقود الخروج."""
    from src.org import cli as org_cli
    rest = list(args._unrecognized) if hasattr(args, "_unrecognized") else []
    return org_cli.main(rest)


_HANDLERS = {
    "radar": _cmd_radar,
    "index-ingest": _cmd_index_ingest,
    "index-query": _cmd_index_query,
    "sandbox": _cmd_sandbox,
    "tickets": _cmd_tickets,
    "webqa": _cmd_webqa,
    "dashboard": _cmd_dashboard,
    "org": _cmd_org,
}


def run_ops_command(argv: Sequence[str]) -> int:
    """تشغيل أمر تشغيلي من قائمة وسائط — نقطة الاختبار والتوصيل معًا.

    التوصيل في ``src/cli/main.py`` سطران: أول ``ops`` في الوسائط
    يُحوّل إلى هذه الدالة بما بعدها — لا إعادة تحليل ولا تفريق.
    """
    parser = _build_parser()
    try:
        args, unrecognized = parser.parse_known_args(list(argv))
        args._unrecognized = unrecognized  # noqa: SLF001 — تمرير لتفويض org
    except SystemExit as exc:  # خطأ استخدام argparse — عقد خروج موحّد
        print("استخدام غير صحيح — راجع nexus ops --help", file=sys.stderr)
        return 1 if exc.code else 0
    if unrecognized and args.ops_command != "org":
        # وسائط غير معلومة مرفوضة لكل الأوامر إلا التفويض org — لا صمت
        print(f"وسائط غير معلومة: {unrecognized} — راجع nexus ops --help",
              file=sys.stderr)
        return 1
    if not args.ops_command:
        parser.print_help()
        return 1
    handler = _HANDLERS[args.ops_command]
    try:
        return handler(args)
    except Exception as exc:  # noqa: BLE001 — حدود CLI تُطبع لا تُرمى
        print(f"خطأ: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    """بناء محلّل أوامر ops — كل أمر مع وسائطه المعلنة."""
    parser = argparse.ArgumentParser(
        prog="nexus ops", description="الطبقة التشغيلية الداخلية — أوامر موحّدة"
    )
    sub = parser.add_subparsers(dest="ops_command")

    p = sub.add_parser("radar", help="دورة رصد (كتالوغي بلا شبكة افتراضيًا)")
    p.add_argument("--cadence", default="morning", choices=["morning", "evening"])
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--config", help="ملف إعدادات JSON اختياري")
    p.add_argument("--live", action="store_true", help="جلب حي عبر http_fetch")

    p = sub.add_parser("index-ingest", help="إدخال ملف نصي إلى الفهرس")
    p.add_argument("path")
    p.add_argument("--doc-id", default=None)
    p.add_argument("--acl", default="team:all")
    p.add_argument("--ttl", type=int, default=0)
    p.add_argument("--db", default=DEFAULT_DB_PATH)

    p = sub.add_parser("index-query", help="استرجاع بميزانية توكن")
    p.add_argument("query")
    p.add_argument("--budget", type=int, default=1500)
    p.add_argument("--acl", default="team:all")
    p.add_argument("--db", default=DEFAULT_DB_PATH)

    p = sub.add_parser("sandbox", help="فحص هدف وحكم ثلاثي")
    p.add_argument("--target", required=True)
    p.add_argument("--path", help="مسار ملف/مجلد للفحص الساكن")
    p.add_argument("--requirements", help="ملف تبعيات للتدقيق")
    p.add_argument("--probe", help="كود مسبار آمن للتنفيذ المعزول")
    p.add_argument("--db", default=DEFAULT_DB_PATH)

    p = sub.add_parser("tickets", help="قائمة التذاكر أو تذكرة واحدة")
    p.add_argument("--state", default=None)
    p.add_argument("--ticket-id", default=None)
    p.add_argument("--db", default=DEFAULT_DB_PATH)

    p = sub.add_parser("webqa", help="بوابة فحص ويب على مجلد")
    p.add_argument("path")
    p.add_argument("--db", default=DEFAULT_DB_PATH)

    p = sub.add_parser("dashboard", help="اللوحة الواحدة")
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--outdir", default=DEFAULT_REPORT_DIR)

    p = sub.add_parser("org", help="التنظيم الهندسي الذاتي — أوامره مع org --help")
    # بقية وسائط org تُحلَّل في src/org/cli.py — التفويض هنا سطر واحد
    return parser
