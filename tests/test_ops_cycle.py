"""اختبار الدورة الكاملة — من الرادار إلى التقرير، والمحاكاة المعلنة للمثال 8.

المثال المرجعي من الخطة: 06:00 إشارة ← 06:05 تذكرة ← 06:10 حكم عزل ←
06:15 تحديث التذكرة بالحكم ← 09:00 مراجعة بشرية ← ملخص واحد للوحة.
هذا الاختبار يمشي السلسلة كلها على مخزن واحد ويثبت أن كل مكوّن
يكتب بعقود الموحّدة لا بكود لصق.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.ops import OpsStore
from src.ops.cli import run_ops_command
from src.ops.dashboard import OpsDashboard
from src.ops.radar import OpsRadar, RadarSource
from src.ops.tickets import TicketBoard
from src.ops.verdict import VerdictEngine
from src.ops.webqa import OpsWebQA


def test_full_cycle_radar_to_report(tmp_path: Path) -> None:
    """السلسلة الكاملة على مخزن واحد — كل مخرج يصبح مدخلًا بلا تحويل يدوي."""
    db = tmp_path / "ops.db"
    store = OpsStore(db)

    # 06:00 — الرادار يجد حزمة جديدة بدرجة عالية.
    radar = OpsRadar(store, sources=(RadarSource(
        "pypi", "packages", "morning", "https://pypi.org/newest", ("llm",)
    ),))
    result = radar.run("morning", fetcher=lambda s: [
        {"title": "أداة وكلاء LLM جديدة", "url": "https://pypi.org/pkg/agent-tool"}
    ])
    assert result.items_stored == 1
    top = store.list_signals(limit=1)[0]

    # 06:05 — الإشارة تصير تذكرة (origin=radar).
    board = TicketBoard(store)
    ticket = board.open_ticket(
        "radar", f"مراجعة إشارة: {top.title}",
        {"what": "إشارة عالية الدجة", "why": "أداة وكلاء ذات صلة مباشرة",
         "risk": "low", "tests": ["sandbox_checks"],
         "rollback": "إغلاق التذكرة يكفي"},
    )
    assert ticket.origin == "radar" and ticket.branch == f"t/{ticket.id}"

    # 06:10 — العزل يفحص الحزمة ويفتح حكمًا غير محسوم بأدلة.
    engine = VerdictEngine(store)
    verdict = engine.evaluate(
        target="agent-tool@0.1",
        requirements="agent-tool",  # غير مثبّتة ⇒ غير محسوم لا مؤكَّد
        probe_code="print('safe-probe-ok')",
    )
    assert verdict.verdict == "inconclusive" and verdict.needs_ticket

    # 06:15 — التذكرة تُحدَّث بحكم العزل وتتقدم في خطها.
    verdict_ticket = engine.ensure_ticket(verdict)
    assert verdict_ticket is not None
    board.advance(ticket.id, "branched", actor="agent", note="بدء التنفيذ")
    board.advance(ticket.id, "executed", actor="agent",
                  note=f"حكم العزل: {verdict.verdict}")
    board.advance(ticket.id, "reported", actor="agent")

    # 06:20 — فحص الويب يُمرَّر ويُسجَّل في المخزن نفسه.
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        '<!DOCTYPE html><html lang="ar"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src self">'
        "</head><body><p>سليم</p></body></html>", encoding="utf-8",
    )
    gate = OpsWebQA(store).run(site)
    assert gate.passed

    # 09:00 — مراجع بشري يراجع تذكرة الحكم عبر الخط القانوني ثم يدمج.
    for nxt, actor in (("branched", "agent"), ("executed", "agent"),
                       ("reported", "agent"), ("reviewed", "human")):
        board.advance(verdict_ticket.id, nxt, actor=actor)
    board.allow_publish(verdict_ticket.id, actor="human")
    merged = board.advance(verdict_ticket.id, "merged", actor="human",
                           ci_green=True, note="مراجعة كاملة + CI أخضر")
    assert merged.state == "merged" and merged.publish_allowed

    # 09:30 — ملخص واحد للوحة يغطي إشارات اليوم وحكمًا وتذكرة وبوابة.
    dashboard = OpsDashboard(store, outdir=tmp_path / "reports" / "ops")
    digest = dashboard.build_cycle_digest()
    files = dashboard.write()
    assert files["markdown"].is_file()
    summary = digest.payload["summary"]
    assert "أداة وكلاء LLM جديدة" in summary
    markdown = files["markdown"].read_text(encoding="utf-8")
    assert "merged: 1" in markdown
    assert "نجحت" in markdown

    # سجل التدقيق يحكي القصة كاملة — كل قرار له أثر موثق.
    actions = [e["action"] for e in store.tail_audit(50)]
    for expected in ("signal.stored", "ticket.opened", "verdict.recorded",
                     "ticket.advance", "gate.recorded", "digest.recorded"):
        assert expected in actions


def test_cli_commands_drive_the_same_store(tmp_path: Path,
                                           capsys: Any) -> None:
    """أوامر CLI تعمل على المخزن نفسه — اللوحة تقرأ ما كتبه الساندبوكس."""
    db = tmp_path / "ops-cli.db"

    def out() -> str:
        return capsys.readouterr().out

    # sandbox: ملف بسرّ ⇒ حكم مؤكَّد ⇒ تذكرة تلقائية (رمز خروج 2).
    pkg = tmp_path / "pkg.py"
    pkg.write_text("K='ghp_" + "a" * 30 + "'", encoding="utf-8")
    rc = run_ops_command(["sandbox", "--target", "pkg@1", "--path", str(pkg),
                          "--db", str(db)])
    assert rc == 2
    assert "تذكرة مفتوحة" in out()

    # tickets: القائمة تُظهر التذكرة الآلية.
    rc = run_ops_command(["tickets", "--db", str(db)])
    assert rc == 0 and "نشر محجوب" in out()

    # index: إدخال ثم استرجاع بميزانية.
    doc = tmp_path / "doc.md"
    doc.write_text("دليل التشغيل الداخلي عن الوكلاء والذاكرة.", encoding="utf-8")
    assert run_ops_command(["index-ingest", str(doc), "--db", str(db)]) == 0
    assert run_ops_command(["index-query", "الوكلاء", "--db", str(db)]) == 0
    assert "citations" in out()

    # dashboard: يكتب التقرير ويطبع اللوحة.
    assert run_ops_command(["dashboard", "--db", str(db),
                            "--outdir", str(tmp_path / "r")]) == 0
    assert (tmp_path / "r" / "dashboard.md").is_file()

    # radar: دورة كتالوغية بلا شبكة تعمل من CLI أيضًا.
    assert run_ops_command(["radar", "--cadence", "morning",
                            "--db", str(db)]) == 0
    assert "sources_ok" in out()

    # webqa: مجلد سليم يمر، وفاشل يعيد 1 ويفتح تذكرة.
    good = tmp_path / "good"
    good.mkdir()
    (good / "i.html").write_text(
        '<!DOCTYPE html><html lang="ar"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="x">'
        "</head><body><p>س</p></body></html>", encoding="utf-8")
    assert run_ops_command(["webqa", str(good), "--db", str(db)]) == 0
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "i.html").write_text("<html><img></html>", encoding="utf-8")
    assert run_ops_command(["webqa", str(bad), "--db", str(db)]) == 1


def test_cli_errors_reported_not_raised(tmp_path: Path) -> None:
    """فشل CLI يُطبع برمز خروج 1 — لا استثناءات متطايرة للطرفية."""
    db = tmp_path / "x.db"
    assert run_ops_command(["sandbox", "--target", "x",
                            "--path", str(tmp_path / "ghost"),
                            "--db", str(db)]) == 1
    assert run_ops_command(["webqa", str(tmp_path / "no-dir"),
                            "--db", str(db)]) == 1
    assert run_ops_command([]) == 1
    assert run_ops_command(["nonexistent-cmd"]) == 1
    assert run_ops_command(["tickets", "--ticket-id", "T-1",
                            "--db", str(db)]) == 1
    assert run_ops_command(["index-ingest", str(tmp_path / "missing.md"),
                            "--db", str(db)]) == 1
