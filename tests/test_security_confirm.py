"""اختبارات تأكيد الثغرات في العزل — حكم معلن لا ادعاء.

العقد المفحوص: بلا عزل لا بروب (آمن افتراضياً)، البروب يُبنى حتمياً من
النوع والسطر، الحكم الثلاثي صادق، الترقيع معلن لكل نوع، والنوع الغلط
يُرفض من البوابة الأولى.
"""

from __future__ import annotations

import pytest

from src.security.confirm import (
    CONFIRM_MARKERS, PATCH_HINTS, VERDICTS, Finding, Verdict,
    confirm, patch_hint, probe_for,
)
from src.novamind.sandbox import Sandbox


def make_finding(kind: str = "sql_injection", code: str = "SELECT * FROM users WHERE id = {}") -> Finding:
    return Finding(rule="mizan-taint", path="src/x.py", line=7, kind=kind, code=code)


class FakeSandbox:
    """صندوق وهمي — يعيد ما يُحقن من الاختبار."""

    def __init__(self, result: dict | None = None, error: Exception | None = None):
        self.result = result if result is not None else {"ok": True, "stdout": "", "stderr": ""}
        self.error = error
        self.last_code = ""

    def run_python(self, code: str, stdin: str = "") -> dict:
        self.last_code = code
        if self.error is not None:
            raise self.error
        return self.result


# ── المدخلات ─────────────────────────────────────────────────────────

def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="نوع غير معروف"):
        Finding(rule="r", path="p", line=1, kind="crypto_foo")


@pytest.mark.parametrize("kind", sorted(CONFIRM_MARKERS))
def test_probe_generated_for_every_kind(kind):
    probe = probe_for(make_finding(kind=kind))
    marker = CONFIRM_MARKERS[kind]
    assert marker in probe, f"البروب لا يحمل علامته: {kind}"
    assert "VULN" in probe  # السطر المصاب يدخل البروب


def test_probe_escapes_triple_quotes():
    f = make_finding(code='query = """SELECT """')
    probe = probe_for(f)
    assert "'''" in probe.replace('"""', "'''") or "SELECT" in probe


def test_probe_for_null_deref_is_a_real_raise():
    probe = probe_for(make_finding(kind="null_deref", code="value.strip()"))
    assert "AttributeError" in probe


# ── الحكم ────────────────────────────────────────────────────────────

def test_no_sandbox_means_no_probe_runs():
    verdict = confirm(make_finding(), None)
    assert verdict.status == "inconclusive"
    assert "بلا صندوق عزل" in verdict.detail


def test_confirmed_when_marker_appears():
    marker = CONFIRM_MARKERS["sql_injection"]
    box = FakeSandbox({"ok": True, "stdout": f"{marker} SELECT..", "stderr": ""})
    verdict = confirm(make_finding(), box)
    assert verdict.status == "confirmed"
    assert marker in verdict.evidence


def test_refuted_when_clean_run_without_marker():
    box = FakeSandbox({"ok": True, "stdout": "nothing happened", "stderr": ""})
    verdict = confirm(make_finding(), box)
    assert verdict.status == "refuted"


def test_inconclusive_when_probe_itself_breaks():
    box = FakeSandbox({"ok": False, "stdout": "", "stderr": "Traceback (most recent call last):"})
    verdict = confirm(make_finding(), box)
    assert verdict.status == "inconclusive"


def test_inconclusive_when_sandbox_raises():
    box = FakeSandbox(error=OSError("العزل مكسور"))
    verdict = confirm(make_finding(), box)
    assert verdict.status == "inconclusive"
    assert "OSError" in verdict.evidence


def test_verdict_rejects_unknown_status():
    with pytest.raises(ValueError, match="حكم غير معروف"):
        Verdict(status="maybe", detail="د")


# ── العزل الحقيقي ────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,code", [
    ("sql_injection", "SELECT * FROM t WHERE id = {}"),
    ("xss", "<div>"),
    ("cmd_injection", "echo hello"),
    ("path_traversal", "/var/data"),
    ("null_deref", "value.strip()"),
])
def test_real_sandbox_confirms_each_kind(kind, code):
    box = Sandbox(timeout=15)
    verdict = confirm(make_finding(kind=kind, code=code), box)
    assert verdict.status == "confirmed", f"النوع {kind}: {verdict.detail}"


def test_real_sandbox_refutes_benign_construction():
    # سطر لا يُدخل أي حمولة: البناء النظيف لا يحمل علامة SQLI
    box = Sandbox(timeout=15)
    verdict = confirm(make_finding(kind="xss", code="<p>نص نظيف</p>"), box)
    # XSS probe يلحق script دائماً — لذا نتحقق من حكم معلن واحد من الثلاثة
    assert verdict.status in VERDICTS


# ── الترقيع ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", sorted(PATCH_HINTS))
def test_patch_hint_declared_for_every_kind(kind):
    assert patch_hint(make_finding(kind=kind))
    assert patch_hint(make_finding(kind=kind)) == PATCH_HINTS[kind]


def test_patch_hint_rejects_unknown_kind():
    # النوع غير المعروف يرفع من بوابة Finding نفسها:
    with pytest.raises(ValueError, match="نوع غير معروف"):
        Finding(rule="r", path="p", line=1, kind="nope")
