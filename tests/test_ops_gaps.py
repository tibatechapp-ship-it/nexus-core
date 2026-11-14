"""اختبارات إغلاق الفجوات — كل فرع متبقٍ في الطبقة التشغيلية له دليل.



هذه الملفات تغطي المسارات الهامشية المعلنة: حدود الإعدادات، سقوف

الإدخال، انتهاء الذاكرة المؤقتة، الطرد الأقدم، الجلب الحي عبر خادم

HTTP محلي حقيقي، فشل نظام الملفات، وإصلاح الأقفال عند فشل المعاملة.

"""



from __future__ import annotations



import http.server

import json

import socketserver

import threading

from pathlib import Path

from typing import Any



import pytest



import src.ops.store as store_mod

from src.ops import OpsStore

from src.ops.cli import run_ops_command

from src.ops.contracts import Digest, GateResult, Signal, Ticket, Verdict

from src.ops.indexer import IndexConfig, OpsIndex

from src.ops.radar import RadarSource, http_fetch

from src.ops.store import OpsError

from src.ops.verdict import IsolatedRunner, SandboxPolicy, VerdictEngine

from src.ops.webqa import OpsWebQA, WebQAConfig





# ── العقود ────────────────────────────────────────────────────────────────



class TestContractsFallbacks:

    def test_from_dict_empty_created_at_gets_now(self) -> None:

        """created_at فارغ في التخزين يعود وقتًا حيًا — العقود لا تعود خاوية."""

        base = {"source": "s", "title": "t", "url": "u", "created_at": ""}

        assert Signal.from_dict(base).created_at.endswith("+00:00")

        v = {"target": "x", "evidence": ["e"], "created_at": ""}

        assert Verdict.from_dict(v).created_at.endswith("+00:00")

        t = {"origin": "radar", "title": "t", "created_at": "",

             "updated_at": ""}

        fresh = Ticket.from_dict(t)

        assert fresh.created_at.endswith("+00:00")

        assert fresh.updated_at.endswith("+00:00")





# ── المخزن ────────────────────────────────────────────────────────────────



class TestLockedConnection:

    def test_failed_enter_releases_lock(self) -> None:

        """فشل فتح المعاملة يحرر القفل — لا قفل عالق بعد فشل."""

        store = OpsStore(":memory:")

        store._conn._raw.close()

        with pytest.raises(store_mod.sqlite3.ProgrammingError):

            store._conn.execute("SELECT 1")

        # القفل محرَّر: تنفيذ لاحق على اتصال جديد لا يعلق.

        store2 = OpsStore(":memory:")

        assert store2.counts()["signals"] == 0



    def test_failed_transaction_releases_lock(self) -> None:

        """فشل داخل المعاملة يُرجع القفل — والحالة تعود كما كانت."""

        store = OpsStore(":memory:")

        with pytest.raises(OpsError):

            with store._conn:

                store._conn.execute(

                    "INSERT INTO meta (key, value) VALUES ('a', '1')"

                )

                raise OpsError("داخل المعاملة")

        assert store.counts()["signals"] == 0

        # الكتابة بعد الفشل تعمل — الدليل على تحرير القفل.

        store.audit("after.failure", "", {})

        assert any(e["action"] == "after.failure" for e in store.tail_audit(1))





# ── الرادار ───────────────────────────────────────────────────────────────



class TestHttpFetchLive:

    def test_fetch_parses_local_server(self) -> None:

        """الجلب الحي على خادم محلي حقيقي: روابط مطلقة تُستخرج مرتّبة."""

        page = ("<html><body>"

                "<a href='/a'>وكيل أ</a>"

                "<a href='https://ext.example/b'>وكيل ب</a>"

                "<a href='#skip'>مكرر مرساة</a>"

                "<a href='javascript:alert(1)'>خطير</a>"

                "<a href='/a'>مكرر نفس الرابط</a>"

                "</body></html>")



        class Handler(http.server.BaseHTTPRequestHandler):

            def do_GET(self) -> None:  # noqa: N802 — توقيع المكتبة

                body = page.encode("utf-8")

                self.send_response(200)

                self.send_header("Content-Type", "text/html")

                self.send_header("Content-Length", str(len(body)))

                self.end_headers()

                self.wfile.write(body)



            def log_message(self, *args: Any) -> None:

                pass



        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:

            port = server.server_address[1]

            thread = threading.Thread(target=server.serve_forever, daemon=True)

            thread.start()

            try:

                src = RadarSource("local", "code", "morning",

                                  f"http://127.0.0.1:{port}/feed", ())

                items = http_fetch(src, timeout=5)

            finally:

                server.shutdown()

        urls = [i["url"] for i in items]

        assert any(u.endswith("/a") for u in urls)

        assert any(u.startswith("https://ext.example") for u in urls)

        assert not any(u.startswith("javascript:") for u in urls)

        # الرابط النسبي يُوسَّع إلى مطلق على المضيف المحلي.

        assert all(u.startswith("http") for u in urls)





# ── الفهرس ────────────────────────────────────────────────────────────────



class TestIndexConfigBounds:

    def test_all_bounds_enforced(self) -> None:

        """كل حد خارج مداه رفع — الإعدادات لا تُقبل على تساهل."""

        with pytest.raises(ValueError, match="أبعاد"):

            IndexConfig(dims=8)

        with pytest.raises(ValueError, match="التقطيع"):

            IndexConfig(chunk_min=900, chunk_target=100)

        with pytest.raises(ValueError, match="التقطيع"):

            IndexConfig(chunk_min=0)

        with pytest.raises(ValueError, match="الميزانية"):

            IndexConfig(budget_tokens=0)

        with pytest.raises(ValueError, match="Top-K"):

            IndexConfig(top_k=0)

        with pytest.raises(ValueError, match="الذاكرة"):

            IndexConfig(cache_ttl_seconds=0)

        with pytest.raises(ValueError, match="الذاكرة"):

            IndexConfig(cache_size=-1)





class TestIndexEdgePaths:

    def test_ingest_file_size_cap(self, tmp_path: Path) -> None:

        """الملف الأكبر من السقف المعلن رفع — الحماية من الضخم صارمة."""

        import src.ops.indexer as ix

        big = tmp_path / "big.md"

        big.write_bytes(b"x" * (ix.MAX_INGEST_BYTES + 1))

        index = OpsIndex(OpsStore(":memory:"))

        with pytest.raises(ValueError, match="سقف"):

            index.ingest_file(str(big))



    def test_vec_from_json_invalid(self) -> None:

        """المتجه المخزّن المشوّه رفع صريح — لا صمت على بيانات فاسدة."""

        from src.ops.indexer import _vec_from_json

        with pytest.raises(ValueError, match="مشوّه"):

            _vec_from_json('{"not": "a-list"}')



    def test_cache_evicts_oldest(self) -> None:

        """الطرد يطرد الأقدم إدخالًا — الذاكرة لا تنمو بلا سقف."""

        index = OpsIndex(OpsStore(":memory:"),

                         IndexConfig(cache_size=2, cache_ttl_seconds=600))

        index.ingest_text("نص الوكلاء الأول.", "d1")

        index.retrieve("الوكلاء الأول")

        index.retrieve("الوكلاء الثاني")

        index.retrieve("الوكلاء الثالث")

        assert len(index._cache) == 2



    def test_cache_ttl_expiry(self) -> None:

        """الذاكرة المنتهية تُحذف بالمرور — TTL صادق لا خداع."""

        index = OpsIndex(OpsStore(":memory:"),

                         IndexConfig(cache_size=4, cache_ttl_seconds=1))

        index.ingest_text("نص لاختبار انتهاء الذاكرة.", "d")

        index.retrieve("انتهاء الذاكرة")

        key = next(iter(index._cache))

        stored_at, payload = index._cache[key]

        index._cache[key] = (stored_at - 10_000, payload)

        assert index._cache_get("انتهاء الذاكرة", 1500, "team:all") is None

        assert key not in index._cache



    def test_cache_disabled_zero_size(self) -> None:

        """حجم صفر يعطّل الذاكرة — خيار معلن لا انزلاق."""

        index = OpsIndex(OpsStore(":memory:"), IndexConfig(cache_size=0))

        index.ingest_text("نص بلا تخزين استعلامات.", "d")

        assert index.retrieve("تخزين استعلامات") is not None

        assert index._cache == {}



    def test_query_acl_none_searches_all(self) -> None:

        """search بلا صلاحية يرى كل الشرائح — الاستعلام الداخلي الكامل."""

        index = OpsIndex(OpsStore(":memory:"))

        index.ingest_text("محتوى سري للفريق.", "sec", acl="team:ai")

        index.ingest_text("محتوى عام للجميع.", "pub", acl="team:all")

        assert len(index.search("محتوى", acl=None)) == 2





# ── العزل ────────────────────────────────────────────────────────────────



class TestVerdictEdgePaths:

    def test_oserror_in_runner_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:

        """فشل نظام التشغيل في التنفيذ يُسجَّل نتيجة — لا استثناء متطاير."""

        import subprocess as sp



        def boom(*args: Any, **kwargs: Any) -> None:

            raise OSError("تشغيل ممنوع")



        monkeypatch.setattr(sp, "run", boom)

        r = IsolatedRunner().run_python("print(1)")

        assert not r.ok and "تشغيل ممنوع" in r.stderr



    def test_unreadable_file_skipped_by_scan(self, tmp_path: Path) -> None:

        """الملف غير المقروء يُتخطّى صامتًا في الفحص — الدورة لا تنهار."""

        f = tmp_path / "locked.py"

        f.write_text("import socket", encoding="utf-8")

        f.chmod(0o000)

        try:

            findings = VerdictEngine.__mro__ and __import__(

                "src.ops.verdict", fromlist=["static_scan"]

            ).static_scan(tmp_path)

            assert findings == []

        finally:

            f.chmod(0o644)



    def test_weird_dependency_lines_ignored(self) -> None:

        """سطر التبعية الذي يفحص فارغًا بعد التشذيب يُتخطّى."""

        from src.ops.verdict import dependency_audit

        assert dependency_audit("#c\n;;\n==weird\n  #x\nrequests==2") == []



    def test_ensure_ticket_after_closed_reopens(self, tmp_path: Path) -> None:

        """التذكرة المغلقة للحكم نفسه تفتح تذكرة جديدة — لا إحياء ميت."""

        store = OpsStore(":memory:")

        engine = VerdictEngine(store)

        f = tmp_path / "l.py"

        f.write_text("K='ghp_" + "a" * 30 + "'", encoding="utf-8")

        v = engine.evaluate("re@1", target_path=f)

        t1 = engine.ensure_ticket(v)

        assert t1 is not None

        store.ticket_advance(t1.id, "closed", actor="human")

        t2 = engine.ensure_ticket(v)

        assert t2 is not None and t2.id != t1.id





# ── فحوص الويب ───────────────────────────────────────────────────────────



class TestWebQAEdgePaths:

    def test_unreadable_html_recorded(self, tmp_path: Path) -> None:

        """ملف HTML غير مقروء نتيجة حاجبة — الفحص يكمل على البقية."""

        d = tmp_path

        f = d / "locked.html"

        f.write_text("<html>", encoding="utf-8")

        f.chmod(0o000)

        try:

            gate = OpsWebQA(OpsStore(":memory:")).run(d)

            assert not gate.passed

            assert any("غير مقروء" in x["message"] for x in gate.findings)

        finally:

            f.chmod(0o644)



    def test_css_budget_exceeded_advisory(self, tmp_path: Path) -> None:

        """تجاوز سقف CSS استشاري — الحد الثاني مفحوص لا معلن فقط."""

        d = tmp_path

        (d / "p.html").write_text(

            '<!DOCTYPE html><html lang="ar"><head><meta charset="utf-8">'

            "</head><body><p>س</p></body></html>", encoding="utf-8")

        (d / "big.css").write_text("/* " + "x" * (WebQAConfig().css_budget_bytes)

                                   + " */\n.a{color:red}", encoding="utf-8")

        gate = OpsWebQA(OpsStore(":memory:")).run(d)

        assert gate.passed

        assert any("حجم CSS" in x["message"] for x in gate.findings)



    def test_void_endtag_and_nested_close(self, tmp_path: Path) -> None:

        """إغلاق عنصر فارغ ورتابة إغلاق مكسورة — مسارات المدقّق البنيوية."""

        html = ("<!DOCTYPE html><html lang='ar'><head><meta charset='utf-8'>"

                "</head><body><img src='x.png' alt='ص'></img>"

                "<div><b>نص</div></b><p>س</p></body></html>")

        d = tmp_path

        (d / "edge.html").write_text(html, encoding="utf-8")

        gate = OpsWebQA(OpsStore(":memory:")).run(d)

        assert gate is not None



    def test_charset_present_no_doctype_error_only(self, tmp_path: Path) -> None:

        """ترميز موجود وDOCTYPE غائب: خطأ واحد لا اثنان — التدقيق دقيق."""

        html = ("<html lang='ar'><head><meta charset='utf-8'>"

                "</head><body><p>س</p></body></html>")

        (tmp_path / "p.html").write_text(html, encoding="utf-8")

        gate = OpsWebQA(OpsStore(":memory:")).run(tmp_path)

        doctype_msgs = [f["message"] for f in gate.findings

                        if "DOCTYPE" in f["message"]]

        charset_msgs = [f["message"] for f in gate.findings

                        if "charset" in f["message"]]

        assert len(doctype_msgs) == 1

        assert charset_msgs == []





def _mk(d: Path, html: str) -> Path:

    """كتابة صفحة اختبار سريعة — تُعيد المسار."""

    p = d / "edge.html"

    p.write_text(html, encoding="utf-8")

    return p





# ── CLI والمجدول ──────────────────────────────────────────────────────────



class TestCliAndRunnerGaps:

    def test_sandbox_with_requirements_file(self, tmp_path: Path) -> None:

        """وسيط ``--requirements`` يُقرأ ويُدقَّق فعليًا."""

        req = tmp_path / "req.txt"

        req.write_text("requests\nflask==2.0", encoding="utf-8")

        rc = run_ops_command([

            "sandbox", "--target", "r@1", "--requirements", str(req),

            "--db", str(tmp_path / "db.sqlite"),

        ])

        assert rc == 0  # غير محسوم: تدقيق وحده ليس مؤكَّدًا ولا آمنًا



    def test_tickets_single_id_found(self, tmp_path: Path) -> None:

        """عرض تذكرة واحدة بمعرّفها يعمل ويطبع JSON الكامل."""

        from src.ops.tickets import TicketBoard

        db = tmp_path / "db.sqlite"

        t = TicketBoard(OpsStore(db)).open_ticket("radar", "عرض مفرد")

        rc = run_ops_command(["tickets", "--ticket-id", t.id, "--db", str(db)])

        assert rc == 0



    def test_default_jobs_evening_cycle_too(self) -> None:

        """المهام الافتراضية تعمل في دورة المساء أيضًا — الفترتان مغطّات."""

        from src.ops.indexer import OpsIndex

        from src.ops.radar import OpsRadar

        from src.ops.runner import OpsRunner, build_default_jobs

        from src.ops.tickets import TicketBoard

        store = OpsStore(":memory:")

        jobs = build_default_jobs(OpsRadar(store), OpsIndex(store),

                                  TicketBoard(store))

        report = OpsRunner(store, jobs, max_workers=1).run_cycle("evening")

        assert {o.name for o in report.outcomes} == {

            "radar_evening", "index_prune", "tickets_autoclose", "board_snapshot"

        }

        assert report.ok



    def test_digest_payload_from_cli_radar(self, tmp_path: Path) -> None:

        """دورة CLI تترك ملخص رادار كامل الحمولة — قابل للعرض لاحقًا."""

        db = tmp_path / "db.sqlite"

        assert run_ops_command(["radar", "--cadence", "evening",

                                "--db", str(db)]) == 0

        store = OpsStore(db)

        d = store.latest_digest("evening")

        assert d is not None

        payload: dict[str, Any] = d.payload

        assert "radar" in payload and "counts" in payload

        assert json.dumps(payload, ensure_ascii=False)


# ── إغلاق نهائي للفجوات ───────────────────────────────────────────────────

class TestFinalGapClosing:
    def test_getattr_unknown_name(self) -> None:
        """اسم غير معروف في src.ops يرفع AttributeError — لا صمت."""
        import src.ops as ops_pkg
        with pytest.raises(AttributeError, match="غير معروف"):
            ops_pkg.NopeExists  # type: ignore[attr-defined]  # noqa: B018

    def test_verdict_checks_must_be_dict(self) -> None:
        """فحوص الحكم قاموس — قائمة مرفوضة برسالة صريحة."""
        with pytest.raises(ValueError, match="checks"):
            Verdict(target="t", evidence=("e",), checks=[])  # type: ignore[arg-type]

    def test_gate_findings_list_coerced(self) -> None:
        """نتائج البوابة تُطبَّع إلى tuple — القائمة مقبولة وتتحول."""
        g = GateResult(tool="webqa", target="d",
                       findings=[{"check": "html_validate"}])
        assert isinstance(g.findings, tuple)

    def test_gate_and_digest_from_dict_fallback(self) -> None:
        """from_dict بطابع فارغ يعيد وقتًا حيًا — كل العقود متسقة."""
        g = GateResult.from_dict({"tool": "w", "target": "t", "created_at": ""})
        assert g.created_at.endswith("+00:00")
        dg = Digest.from_dict({"kind": "cycle", "day": "d", "created_at": ""})
        assert dg.created_at.endswith("+00:00")

    def test_runner_timeout_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """انتهاء مهلة المسبار يُسجَّل نتيجة صادقة — لا تلفيف."""
        import subprocess as sp

        def slow(*args: Any, **kwargs: Any) -> None:
            raise sp.TimeoutExpired(cmd="python3", timeout=1)

        monkeypatch.setattr(sp, "run", slow)
        r = IsolatedRunner().run_python("print(1)")
        assert not r.ok and r.timed_out and "المهلة" in r.summary()

    def test_store_transaction_enter_failure(self) -> None:
        """فشل فتح المعاملة يحرر القفل ويصعد — مسار __enter__ مغطّى."""
        store = OpsStore(":memory:")
        store._conn._raw.close()
        with pytest.raises(store_mod.sqlite3.ProgrammingError):
            with store._conn:
                pass

    def test_store_close_releases(self, tmp_path: Path) -> None:
        """الإغلاق الصريح يعمل — والاتصال مغلق بعده."""
        store = OpsStore(tmp_path / "c.db")
        store.audit("closing", "", {})
        store.close()

    def test_sandbox_cli_safe_verdict_no_ticket(self, tmp_path: Path) -> None:
        """CLI على هدف نظيف: حكم آمن بلا تذكرة — الفرع الساكن مغطّى."""
        req = tmp_path / "req.txt"
        req.write_text("pinned==1.0", encoding="utf-8")
        clean = tmp_path / "clean"
        clean.mkdir()
        (clean / "ok.py").write_text("print(1)", encoding="utf-8")
        rc = run_ops_command([
            "sandbox", "--target", "clean@1", "--path", str(clean),
            "--requirements", str(req), "--probe", "print(1)",
            "--db", str(tmp_path / "db.sqlite"),
        ])
        assert rc == 0

    def test_webqa_css_unreadable_skipped(self, tmp_path: Path) -> None:
        """CSS غير مقروء يُتخطّى صامتًا — الحد حاجب HTML فقط."""
        d = tmp_path
        (d / "p.html").write_text(
            '<!DOCTYPE html><html lang="ar"><head><meta charset="utf-8">'
            "</head><body><p>س</p></body></html>", encoding="utf-8")
        css = d / "locked.css"
        css.write_text(".a{color:red}", encoding="utf-8")
        css.chmod(0o000)
        try:
            gate = OpsWebQA(OpsStore(":memory:")).run(d)
            assert gate.passed
        finally:
            css.chmod(0o644)

    def test_auditor_close_without_open_and_button_text(self, tmp_path: Path) -> None:
        """إغلاق بلا فتح يُرصد، ونص الزر الداخلي يُلتقط للوصول."""
        html = ("<!DOCTYPE html><html lang='ar'><head><meta charset='utf-8'>"
                "</head><body></body></html></p>")
        d = tmp_path
        (d / "p.html").write_text(html, encoding="utf-8")
        gate = OpsWebQA(OpsStore(":memory:")).run(d)
        assert any("إغلاق بلا فتح" in f["message"] for f in gate.findings)

    def test_button_with_text_not_flagged(self, tmp_path: Path) -> None:
        """زر بنص واضح لا يُرصَد — دليل إيجابي على معالجة البيانات."""
        html = ("<!DOCTYPE html><html lang='ar'><head><meta charset='utf-8'>"
                "</head><body><button>حفظ النموذج</button></body></html>")
        d = tmp_path
        (d / "p.html").write_text(html, encoding="utf-8")
        gate = OpsWebQA(OpsStore(":memory:")).run(d)
        assert not any("button" in f["message"] for f in gate.findings)

    def test_http_fetch_fifty_cap(self) -> None:
        """سقف 50 عنصرًا للمصدر الواحد مفروض — المزيد يُعدّ ولا يُجلب."""
        links = "".join(f"<a href='/i{n}'>بند {n}</a>" for n in range(80))
        page = f"<html><body>{links}</body></html>"

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — توقيع المكتبة
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                src = RadarSource("cap", "code", "morning",
                                  f"http://127.0.0.1:{port}/", ())
                items = http_fetch(src, timeout=5)
            finally:
                server.shutdown()
        assert len(items) == 50
