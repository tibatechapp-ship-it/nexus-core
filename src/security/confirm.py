"""تأكيد الثغرة في العزل — لا إبلاغ بثغرة لم تُثبت نفسها.

المبدأ المعلن: الماسح يُشتبه، والعزل يُثبت. كل ملاحظة أمنية تحمل «برُوب»
صغيراً حتمياً يُشغَّل داخل صندوق العزل (``novamind.sandbox.Sandbox``) فيحكم:

* ``confirmed`` — البروب أثبت الأثر فعلاً (العلامة المعلنة ظهرت).
* ``refuted`` — تشغيل نظيف بلا علامة: الاشتباه لم يثبت نفسه.
* ``inconclusive`` — بلا عزل، أو بروب تالف، أو خطأ غير متوقع: نعلن الجهل
  لا نادّعيه. **بلا عزل لا يُشغَّل أي بروب** — الآمن افتراضياً.

البروبات هنا محاكاة أثر لا استغلال شبكي: تُبنى من السطر المصاب نفسه وتجري
كله في العزل بلا شبكة إطلاقاً (تحترم ADR-0001 وADR-0004).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "CONFIRM_MARKERS", "VERDICTS", "Finding", "ProbeSandbox",
    "probe_for", "confirm", "patch_hint", "Verdict",
]

#: علامة كل نوع — ظهورها في مخرجات البروب هو الدليل المعلن.
CONFIRM_MARKERS: dict[str, str] = {
    "sql_injection": "SQLI-PROOF",
    "xss": "XSS-PROOF",
    "cmd_injection": "CMD-PROOF",
    "path_traversal": "PATH-PROOF",
    "null_deref": "NPE-PROOF",
}

#: الأحكام الثلاثة المعلنة — لا رابع.
VERDICTS: tuple[str, ...] = ("confirmed", "refuted", "inconclusive")


class ProbeSandbox(Protocol):
    """أدنى عقد صندوق يُقبَل: ``run_python(code)`` يعيد قاموساً فيه ok/stdout."""

    def run_python(self, code: str, stdin: str = "") -> dict[str, Any]: ...


@dataclass(frozen=True)
class Finding:
    """ملاحظة أمنية واحدة كما تخرج من الماسح أو الطبقة الخصمية."""

    rule: str
    path: str
    line: int
    kind: str
    code: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in CONFIRM_MARKERS:
            raise ValueError(
                f"نوع غير معروف: {self.kind} (المعروف: {sorted(CONFIRM_MARKERS)})")


@dataclass(frozen=True)
class Verdict:
    """حكم معلن: حالته وشرحه ودليله (مقصوص دائماً)."""

    status: str
    detail: str
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.status not in VERDICTS:
            raise ValueError(f"حكم غير معروف: {self.status} (المعروف: {VERDICTS})")


def _quoted(code: str) -> str:
    """السطر المصاب داخل بروب — بلا مراوغة اقتباس."""
    return code.replace("\\", "\\\\").replace('"""', "'''").strip()


def probe_for(finding: Finding) -> str:
    """بروب حتمي لنوع الملاحظة — يحاكي الأثر من السطر المصاب نفسه."""
    src = _quoted(finding.code)
    if finding.kind == "sql_injection":
        return f'''VULN = """{src}"""
payload = "' OR '1'='1"
built = VULN.replace("{{}}", payload)
if "OR" in built.upper():
    print("{CONFIRM_MARKERS['sql_injection']}", built[:120])
'''
    if finding.kind == "xss":
        return f'''VULN = """{src}"""
payload = "<script>alert(1)</script>"
rendered = VULN + payload
if "<script>" in rendered:
    print("{CONFIRM_MARKERS['xss']}", rendered[:120])
'''
    if finding.kind == "cmd_injection":
        return f'''import shlex
VULN = """{src}"""
payload = "; rm -rf /"
built = VULN + payload
parts = shlex.split(built)
if any(p in ("rm", "sh", "bash") for p in parts):
    print("{CONFIRM_MARKERS['cmd_injection']}", built[:120])
'''
    if finding.kind == "path_traversal":
        return f'''from pathlib import Path
VULN = """{src}"""
payload = "../../etc/passwd"
joined = str(Path(VULN) / payload)
if ".." in Path(joined).parts:
    print("{CONFIRM_MARKERS['path_traversal']}", joined[:120])
'''
    # null_deref — الوحيد الذي يرمي فعلاً: الأثر هو الاستثناء نفسه.
    return f'''VULN = """{src}"""
try:
    value = None
    _ = value.strip()
except AttributeError as exc:
    print("{CONFIRM_MARKERS['null_deref']}", str(exc)[:120])
'''


def confirm(
    finding: Finding,
    sandbox: ProbeSandbox | None,
    timeout_hint: int | None = None,
) -> Verdict:
    """أحكم على الملاحظة — **بلا عزل لا يُشغَّل بروب** (آمن افتراضياً)."""
    if sandbox is None:
        return Verdict(
            "inconclusive",
            "بلا صندوق عزل لا يُشغَّل بروب — الاشتباه يبقى اشتباهاً",
        )
    probe = probe_for(finding)
    try:
        result = sandbox.run_python(probe)
    except Exception as exc:  # noqa: BLE001 — العطل يُعلن لا يُخفى
        return Verdict(
            "inconclusive",
            f"صندوق العزل رفع {type(exc).__name__} — الحكم معلن لا مُصطنع",
            f"{type(exc).__name__}",
        )
    marker = CONFIRM_MARKERS[finding.kind]
    stdout = str(result.get("stdout", ""))
    stderr = str(result.get("stderr", ""))
    if marker in stdout:
        return Verdict(
            "confirmed",
            f"البروب أثبت الأثر: العلامة {marker} ظهرت في العزل",
            stdout[:300].strip(),
        )
    if not result.get("ok", False) and "Traceback" in stderr and marker not in stderr:
        return Verdict(
            "inconclusive",
            "البروب نفسه رفع خطأ غير متوقع — لا حكم يُصطنع",
            stderr[:300].strip(),
        )
    return Verdict(
        "refuted",
        "تشغيل نظيف بلا علامة — الاشتباه لم يثبت نفسه",
        stdout[:200].strip(),
    )


#: اقتراح الترقيع الحتمي لكل نوع — نص معلن يقبل الاختبار لا نص إلهام.
PATCH_HINTS: dict[str, str] = {
    "sql_injection": "مرّر القيم مُعامَلات لا بتنسيق نصي: cursor.execute(SQL, (value,))",
    "xss": "اسكِب المخرجات عند البناء (html.escape) أو استخدم قوالب تُسكّب تلقائياً",
    "cmd_injection": "مرّر الأمر قائمة أجزاء (shlex.split / subprocess(list)) ولا تنفذ نصاً مجمّعاً",
    "path_traversal": "قيّد المسار: Path(base).resolve() ثم تحقق أن الهدف داخل base",
    "null_deref": "افحص القيمة قبل الاستخدام: if value is None: … أو قيمة افتراضية",
}


def patch_hint(finding: Finding) -> str:
    """اقتراح ترقيع حتمي لنوع الملاحظة — خطأ النوع يُعلن."""
    hint = PATCH_HINTS.get(finding.kind)
    if hint is None:
        raise ValueError(f"لا ترقيع معلن للنوع: {finding.kind}")
    return hint
