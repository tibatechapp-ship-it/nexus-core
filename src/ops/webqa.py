"""فحوص معايير الويب — بوابة CI واحدة: حاجبة تمنع الدمج واستشارية تحسّن.

القواعد المعلنة المطبَّقة حرفيًا:

1. الفحوص مدمجة في CI فقط — لا إشعارات فورية ولا عمال خلفية.
2. الفصل الصريح: «خطأ يمنع الدمج» (``html_validate`` و``axe_critical``)
   عن «تحسين لاحق» (CSS والميزانية وCSP) — حتى لا يكسر التحسين الواجهة
   ولا يخفي التحسين خطأً حاجبًا.
3. فشل بوابة حاجبة يفتح تذكرة تلقائيًا مع النتائج موثّقة.
4. كل نتيجة تُخزَّن في المخزن الواحد وتُعرض في اللوحة.

الحد الصادق: هذه فحوص بنيوية بـ ``html.parser`` لا محرك متصفح —
تلتقط الخلل البنيوي وإمكانية الوصول الحرجة (صور بلا وصف، مدخلات
بلا تسمية) ولا تقيس الأداء الفعلي؛ الميزانية حدود حجم معلنة
لا Lighthouse حقيقي.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from src.ops.contracts import GateResult, Ticket
from src.ops.store import OpsStore

__all__ = [
    "BLOCKING_CHECKS",
    "ADVISORY_CHECKS",
    "BUDGETS",
    "WebQAConfig",
    "OpsWebQA",
    "VOID_ELEMENTS",
]

#: الفحوص الحاجبة — فشلها يمنع الدمج ويفتح تذكرة.
BLOCKING_CHECKS: tuple[str, ...] = ("html_validate", "axe_critical")

#: الفحوص الاستشارية — تُسجَّل وتُعرض ولا تمنع شيئًا.
ADVISORY_CHECKS: tuple[str, ...] = ("css_validate", "lighthouse_budget", "csp_check")

#: حدود الحجم المعلنة (بايت) — استشارية دائمًا.
BUDGETS: dict[str, int] = {"html": 200_000, "css": 100_000}

#: العناصر الفارغة — لا تُدفع على المكدس في فحص التوازن.
VOID_ELEMENTS: frozenset[str] = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})


@dataclass(frozen=True)
class WebQAConfig:
    """إعدادات الفحص — الحدود والأسماء معلنة ولا مفاجآت."""

    html_budget_bytes: int = BUDGETS["html"]
    css_budget_bytes: int = BUDGETS["css"]
    open_tickets: bool = True

    def __post_init__(self) -> None:
        if self.html_budget_bytes < 1 or self.css_budget_bytes < 1:
            raise ValueError("حدود الحجم لا تقل عن بايت واحد")


class _PageAuditor(HTMLParser):
    """مدقّق صفحة واحد — توازن الوسوم وصور/مدخلات الوصول في مرور واحد."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.stack: list[str] = []
        self.has_doctype = False
        self.has_charset = False
        self.html_lang = ""
        self.label_for: set[str] = set()
        self.button_depth = 0
        self.button_text = ""

    def handle_decl(self, decl: str) -> None:
        if "doctype" in decl.lower():
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = a.get("lang", "")
        if tag == "meta" and a.get("charset"):
            self.has_charset = True
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "img" and "alt" not in a:
            self.errors.append("img بلا alt — صورة غير موصوفة")
        if tag == "input" and a.get("type") != "hidden":
            if not (a.get("aria-label") or a.get("title")
                    or (a.get("id") in self.label_for and a.get("id"))):
                self.errors.append("input بلا تسمية — حقل بلا وصول")
        if tag == "button":
            self.button_depth += 1
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self.button_depth = max(0, self.button_depth - 1)
            if not self.button_text.strip():
                self.errors.append("button بلا نص — زر بلا اسم وصول")
            self.button_text = ""
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append(f"إغلاق بلا فتح: </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.errors.append(f"ترتيب إغلاق مكسور عند </{tag}>")
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        # وسما فُتح ولم يُغلق يُحاسب في close()

    def handle_data(self, data: str) -> None:
        if self.button_depth > 0:
            self.button_text += data

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("وسوم فُتحت بلا إغلاق: " + ", ".join(self.stack[:5]))


class OpsWebQA:
    """فحص ويب موحّد — مسار واحد: ملفات ← فحوص ← بوابة ← تذكرة إن حاجب."""

    def __init__(self, store: OpsStore, config: WebQAConfig | None = None) -> None:
        self._store = store
        self._config = config or WebQAConfig()

    def run(self, target: str | Path) -> GateResult:
        """فحص مجلد ويب كامل — العائد نتيجة بوابة مخزّنة وجاهزة للعرض."""
        root = Path(target)
        if not root.is_dir():
            raise FileNotFoundError(f"هدف الفحص ليس مجلدًا: {root}")
        html_files = sorted(root.rglob("*.html"))
        css_files = sorted(root.rglob("*.css"))
        findings: list[dict[str, str]] = []

        for f in html_files:
            findings.extend(self._check_html(f))
        for f in html_files:
            findings.extend(self._check_a11y(f))
        for f in css_files:
            findings.extend(self._check_css(f))
        findings.extend(self._check_budget(html_files, css_files))
        for f in html_files:
            findings.extend(self._check_csp(f))

        blocking_failed = any(f["check"] in BLOCKING_CHECKS for f in findings)
        gate = GateResult(
            tool="webqa", target=str(root), blocking=True,
            passed=not blocking_failed, findings=tuple(findings),
        )
        self._store.add_gate(gate)
        ticket: Ticket | None = None
        if blocking_failed and self._config.open_tickets:
            from src.ops.tickets import TicketBoard
            board = TicketBoard(self._store)
            ticket = board.open_ticket(
                origin="webqa",
                title=f"بوابة ويب حاجبة فاشلة: {root.name}",
                report={
                    "what": f"{len(findings)} نتيجة منها نتائج حاجبة",
                    "why": " ؛ ".join(f["message"] for f in findings
                                      if f["check"] in BLOCKING_CHECKS)[:400],
                    "risk": "medium",
                    "tests": ["webqa"],
                    "rollback": "لا دمج حتى إصلاح الحاجبات",
                },
            )
            self._store.gate_set_ticket(gate.id, ticket.id)
            return GateResult(
                tool=gate.tool, target=gate.target, blocking=gate.blocking,
                passed=gate.passed, findings=gate.findings,
                ticket_id=ticket.id, id=gate.id, created_at=gate.created_at,
            )
        return gate

    # ── الفحوص الخمسة ─────────────────────────────────────────────────────

    # ── القراءة المحمية ───────────────────────────────────────────────────

    def _read(self, path: Path) -> str | None:
        """قراءة ملف محمية — غير المقروء ``None`` والفحص يكمل على البقية."""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _check_html(self, path: Path) -> list[dict[str, str]]:
        """فحص بنية HTML — توازن الوسوم وDOCTYPE وترميز الحروف."""
        out: list[dict[str, str]] = []
        text = self._read(path)
        if text is None:
            out.append(self._finding("html_validate", "critical", str(path),
                                     f"ملف غير مقروء: {path}"))
            return out
        auditor = _PageAuditor()
        auditor.feed(text)
        auditor.close()
        if not auditor.has_doctype:
            out.append(self._finding("html_validate", "critical", str(path),
                                     "DOCTYPE مفقود"))
        if not auditor.has_charset:
            out.append(self._finding("html_validate", "critical", str(path),
                                     "charset meta مفقود"))
        for err in auditor.errors[:10]:
            out.append(self._finding("html_validate", "critical", str(path), err))
        return out

    def _check_a11y(self, path: Path) -> list[dict[str, str]]:
        """فحص الوصول الحرجة — لغة الصفحة إضافة إلى أخطاء المدقّق."""
        out: list[dict[str, str]] = []
        text = self._read(path)
        if text is None:
            return out  # الملف حُسِب في html_validate — لا تكرار للأدلة
        auditor = _PageAuditor()
        auditor.feed(text)
        auditor.close()
        if not auditor.html_lang:
            out.append(self._finding("axe_critical", "critical", str(path),
                                     "html بلا lang — لغة الصفحة غير معلنة"))
        for err in auditor.errors[:10]:
            out.append(self._finding("axe_critical", "critical", str(path), err))
        return out

    def _check_css(self, path: Path) -> list[dict[str, str]]:
        """فحص CSS استشاري — توازن الأقواس وتوازن التعليقات."""
        out: list[dict[str, str]] = []
        text = self._read(path)
        if text is None:
            return out
        if text.count("{") != text.count("}"):
            out.append(self._finding("css_validate", "advisory", str(path),
                                     f"أقواس CSS غير متوازنة: "
                                     f"{text.count('{')} فتح مقابل {text.count('}')} إغلاق"))
        if text.count("/*") != text.count("*/"):
            out.append(self._finding("css_validate", "advisory", str(path),
                                     "تعليقات CSS غير مغلقة"))
        return out

    def _check_budget(self, html_files: list[Path],
                      css_files: list[Path]) -> list[dict[str, str]]:
        """حدود الحجم استشارية — مجموع الملفات مقابل السقوف المعلنة."""
        out: list[dict[str, str]] = []
        html_bytes = sum(f.stat().st_size for f in html_files)
        css_bytes = sum(f.stat().st_size for f in css_files)
        if html_bytes > self._config.html_budget_bytes:
            out.append(self._finding(
                "lighthouse_budget", "advisory", "",
                f"حجم HTML {html_bytes} بايت يتجاوز السقف "
                f"{self._config.html_budget_bytes}",
            ))
        if css_bytes > self._config.css_budget_bytes:
            out.append(self._finding(
                "lighthouse_budget", "advisory", "",
                f"حجم CSS {css_bytes} بايت يتجاوز السقف "
                f"{self._config.css_budget_bytes}",
            ))
        return out

    def _check_csp(self, path: Path) -> list[dict[str, str]]:
        """فحص CSP استشاري — وجود سياسة أمان المحتوى في كل صفحة."""
        text = self._read(path)
        if text is None:
            return []
        if 'http-equiv="Content-Security-Policy"' not in text:
            return [self._finding("csp_check", "advisory", str(path),
                                  "CSP meta مفقود — سياسة أمان المحتوى غير معلنة")]
        return []

    def _finding(self, check: str, severity: str, file: str,
                 message: str) -> dict[str, str]:
        """بنية النتيجة الموحّدة — نفس المفاتيح في العرض والتقرير والتذكرة."""
        return {"check": check, "severity": severity, "file": file,
                "message": message}
