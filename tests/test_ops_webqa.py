"""اختبارات فحوص الويب — البوابات الحاجبة والاستشارية والتذكرة الآلية."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ops import OpsStore
from src.ops.webqa import BUDGETS, BLOCKING_CHECKS, OpsWebQA, WebQAConfig

GOOD_PAGE = """<!DOCTYPE html>
<html lang="ar">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'">
<title>صفحة سليمة</title>
</head>
<body>
<img src="logo.png" alt="الشعار">
<label for="name">الاسم</label>
<input id="name">
<button>إرسال</button>
</body>
</html>"""


def _write_page(dir_path: Path, html: str, css: str = "",
                name: str = "page.html") -> Path:
    """كتابة صفحة اختبار — وأخت CSS اختياري."""
    (dir_path / name).write_text(html, encoding="utf-8")
    if css:
        (dir_path / "style.css").write_text(css, encoding="utf-8")
    return dir_path


@pytest.fixture()
def qa() -> OpsWebQA:
    """فحص على مخزن ذاكرة — تذاكر مفعّلة."""
    return OpsWebQA(OpsStore(":memory:"))


class TestConfigAndConstants:
    def test_blocking_checks_declared(self) -> None:
        """الفحوص الحاجبة اثنان معلنان — html_validate وaxe_critical."""
        assert set(BLOCKING_CHECKS) == {"html_validate", "axe_critical"}

    def test_budgets_positive(self) -> None:
        """حدود الحجم موجبة معلنة — استشارية دائمًا."""
        assert BUDGETS["html"] > 0 and BUDGETS["css"] > 0
        with pytest.raises(ValueError, match="بايت"):
            WebQAConfig(html_budget_bytes=0)
        with pytest.raises(ValueError, match="بايت"):
            WebQAConfig(css_budget_bytes=0)


class TestGoodPage:
    def test_clean_page_passes_with_zero_findings(self, qa: OpsWebQA,
                                                  tmp_path: Path) -> None:
        """الصفحة السليمة تمر بصفر نتائج — الفحص لا يصنع ضجيجًا."""
        gate = qa.run(_write_page(tmp_path, GOOD_PAGE))
        assert gate.passed and gate.findings == () and gate.blocking

    def test_results_stored_in_single_store(self, qa: OpsWebQA,
                                            tmp_path: Path) -> None:
        """كل نتيجة بوابة تُخزَّن في المخزن الواحد — اللوحة تقرأها لاحقًا."""
        qa.run(_write_page(tmp_path, GOOD_PAGE))
        gates = qa._store.list_gates()
        assert len(gates) == 1 and gates[0].tool == "webqa"


class TestBlockingFailures:
    def test_missing_doctype_charset_block(self, qa: OpsWebQA,
                                           tmp_path: Path) -> None:
        """DOCTYPE والترميز حاجبان — غيابهما يمنع الدمج."""
        html = "<html lang='ar'><body><p>نص</p></body></html>"
        gate = qa.run(_write_page(tmp_path, html))
        checks = {f["check"] for f in gate.findings}
        assert "html_validate" in checks and not gate.passed

    def test_unbalanced_tags_block(self, qa: OpsWebQA,
                                   tmp_path: Path) -> None:
        """الوسم غير المغلق حاجب — التوازن البنيوي شرط."""
        html = GOOD_PAGE.replace("</body>", "<div><span></body>")
        gate = qa.run(_write_page(tmp_path, html))
        assert not gate.passed

    def test_a11y_critical_blocks(self, qa: OpsWebQA,
                                  tmp_path: Path) -> None:
        """صورة بلا وصف وحقل بلا تسمية ولغة مفقودة — كلها حاجبة."""
        html = "<!DOCTYPE html><html><head><meta charset='utf-8'></head>" \
               "<body><img src='a.png'><input><button></button></body></html>"
        gate = qa.run(_write_page(tmp_path, html))
        checks = {f["check"] for f in gate.findings}
        assert "axe_critical" in checks and not gate.passed

    def test_blocking_failure_opens_ticket(self, qa: OpsWebQA,
                                           tmp_path: Path) -> None:
        """فشل الحاجبة يفتح تذكرة webqa مرتبطة بالبوابة — القاعدة كاملة."""
        html = "<html><body><p>ناقص</p></body></html>"
        gate = qa.run(_write_page(tmp_path, html))
        assert gate.ticket_id
        t = qa._store.ticket_get(gate.ticket_id)
        assert t is not None and t.origin == "webqa"
        assert qa._store.list_gates()[0].ticket_id == gate.ticket_id

    def test_tickets_disabled_option(self, tmp_path: Path) -> None:
        """تعطيل التذاكر خيار معلن — البوابة تسجل ولا تفتح تذكرة."""
        qa = OpsWebQA(OpsStore(":memory:"), WebQAConfig(open_tickets=False))
        html = "<html><body><p>ناقص</p></body></html>"
        gate = qa.run(_write_page(tmp_path, html))
        assert not gate.passed and gate.ticket_id is None


class TestAdvisoryFindings:
    def test_css_imbalance_advisory_only(self, qa: OpsWebQA,
                                         tmp_path: Path) -> None:
        """قوس CSS غير متوازن استشاري — لا يمنع الدمج."""
        css = ".a { color: red;"
        gate = qa.run(_write_page(tmp_path, GOOD_PAGE, css=css))
        assert gate.passed
        assert any(f["check"] == "css_validate" for f in gate.findings)

    def test_unclosed_css_comment_advisory(self, qa: OpsWebQA,
                                           tmp_path: Path) -> None:
        """التعليق غير المغلق استشاري — يُعدّ ولا يحجب."""
        css = "/* تعليق معلق"
        gate = qa.run(_write_page(tmp_path, GOOD_PAGE, css=css))
        assert gate.passed

    def test_html_budget_exceeded_advisory(self, qa: OpsWebQA,
                                           tmp_path: Path) -> None:
        """تجاوز سقف HTML استشاري — حجم كبير لا يمنع الدمج."""
        big = GOOD_PAGE + "<!-- " + "x" * (WebQAConfig().html_budget_bytes) + " -->"
        gate = qa.run(_write_page(tmp_path, big))
        assert gate.passed
        assert any(f["check"] == "lighthouse_budget" for f in gate.findings)

    def test_missing_csp_advisory(self, qa: OpsWebQA,
                                  tmp_path: Path) -> None:
        """غياب CSP استشاري — يُعلن ولا يحجب."""
        html = GOOD_PAGE.replace(
            '<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">',
            "")
        gate = qa.run(_write_page(tmp_path, html))
        assert gate.passed
        assert any(f["check"] == "csp_check" for f in gate.findings)


class TestInputValidation:
    def test_non_directory_rejected(self, qa: OpsWebQA,
                                    tmp_path: Path) -> None:
        """هدف الفحص مجلد — ملف أو غائب رفع صريح."""
        with pytest.raises(FileNotFoundError):
            qa.run(tmp_path / "ghost-dir")
        with pytest.raises(FileNotFoundError):
            qa.run(_write_page(tmp_path / "asdir", GOOD_PAGE) / "page.html")

    def test_unreadable_file_recorded(self, qa: OpsWebQA,
                                      tmp_path: Path) -> None:
        """الملف غير المقروء نتيجة مسجلة — لا انهيار دورة الفحص."""
        d = _write_page(tmp_path, GOOD_PAGE)
        locked = d / "locked.html"
        locked.write_bytes(b"\xff\xfe\x00binary")
        gate = qa.run(d)
        assert gate is not None  # الفحص اكتمل — الفاسد نتيجة لا استثناء
