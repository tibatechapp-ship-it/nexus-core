"""قسم الأمن — أسرار، تبعيات، حقن مطالبات، ونموذج تهديد مصغّر.

القواعد المعلنة:

* **الأسرار تُكتشف ولا تُطبع**: كل نص مُمسوح يعيد مواضع فقط مع نص
  مُنقّح (``****REDACTED****``) — القيمة الحقيقية لا تخرج من هذا
  الملف إلى السجلات أو التقارير إطلاقًا.
* **حقن المطالبات يُعزَل**: محتوى المستودع غير موثوق؛ أي سطر يشبه
  توجيهًا للنموذج يُستبدل بعلامة خاملة ويُغلَّف بحد ثقة صريح قبل
  وصوله لأي وكيل.
* **تدقيق التبعيات على مجموعة معلنة**: مجموعة تنبيهات تعليمية مضمّنة
  مع مقارنة إصدارات صريحة — الإنتاج يوصل مصدرًا خارجيًا (OSV/NVD)
  بنفس الواجهة دون تعديل الفحص.
* **لا تنفيذ لكود المستودع أثناء الفحص الساكن** — هذا الملف لا يشغّل
  شيئًا؛ التنفيذ معزول في ``sandbox`` فقط.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "ADVISORIES",
    "DependencyFinding",
    "InjectionGuard",
    "InjectionHit",
    "REDACTED",
    "SecretHit",
    "ThreatModel",
    "check_dependencies",
    "parse_dependencies",
    "scan_text_for_secrets",
]

#: نص التنقيح — القيمة الحقيقية لا تُكتب في أي مخرج.
REDACTED = "****REDACTED****"

# ── 1: كشف الأسرار ────────────────────────────────────────────────────────

#: أنماط معلنة — كل نمط اسمه ومصدره واضحان، لا مطابقة عمياء.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_pem",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("generic_secret_assignment", re.compile(
        r"(?i)\b(api[_-]?key|secret|password|token|credential)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9_\-]{10,}")),
]


@dataclass(frozen=True)
class SecretHit:
    """سر مكتشف — الموضع والنوع فقط، والنص مُنقّح دائمًا."""

    kind: str
    file: str
    line: int
    col: int
    snippet: str


def scan_text_for_secrets(text: str, path: str) -> list[SecretHit]:
    """مسح نص واحد — كل مطابقة تُرجع منقّحة بلا قيمة حقيقية."""
    hits: list[SecretHit] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS:
            for m in pattern.finditer(line):
                start, end = m.span()
                window = line[max(0, start - 8):end + 8].strip()
                snippet = window.replace(m.group(0), REDACTED)
                hits.append(SecretHit(kind=kind, file=path, line=line_no,
                                      col=start + 1, snippet=snippet))
    return hits


def scan_dir_for_secrets(root: Path,
                         ignore_dirs: Iterable[str] = (
                             ".git", "node_modules", ".venv", "__pycache__",
                             "data", "dist", "build")) -> list[SecretHit]:
    """مسح مجلد — يقرأ ملفات نصية فقط ويتخطى المجلدات المعلنة."""
    ignore = set(ignore_dirs)
    hits: list[SecretHit] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in ignore for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        hits.extend(scan_text_for_secrets(text, rel))
    return hits


# ── 2: تدقيق التبعيات ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Advisory:
    """تنبيه واحد معلن — حزمة، حد إصابة، مرجع، خطورة."""

    package: str
    affected_below: str      # الإصابة أدنى من هذا الإصدار (مثل 3.0.3)
    cve: str
    severity: str
    summary: str


#: مجموعة تعليمية مضمّنة — الإنتاج يوصل مصدرًا خارجيًا بنفس الواجهة.
ADVISORIES: tuple[Advisory, ...] = (
    Advisory("werkzeug", "3.0.3", "CVE-2024-34069", "medium",
             "حقن في مصحّح الأخطاء عند تفعيل debug."),
    Advisory("gunicorn", "22.0.0", "CVE-2024-1135", "high",
             "تهريب طلبات HTTP عبر Transfer-Encoding."),
    Advisory("aiohttp", "3.10.2", "CVE-2024-23334", "high",
             "تجاوز مجلدات عبر معالجة الملفات الساكنة."),
    Advisory("cryptography", "42.0.4", "CVE-2024-26130", "high",
             "تجاوز سعة في تحليل الشهادات."),
    Advisory("requests", "2.32.0", "CVE-2024-35195", "medium",
             "تثبيت جلسة مع إعادة استخدام الشهادات."),
)

_DEP_SPEC = re.compile(
    r"^([A-Za-z0-9_.\-]+)\s*(?:[<>=!~]+\s*([A-Za-z0-9_.\-]+))?")


@dataclass(frozen=True)
class DependencyFinding:
    """تبعية مُصابة — الحزمة والإصدار والتنبيه."""

    package: str
    version: str
    advisory: Advisory


def parse_dependencies(text: str) -> dict[str, str]:
    """تحليل requirements مبسّط — أسطر التعلق والروابط تُتخطى."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "git+")):
            continue
        name_part = line.split(";")[0].split("[")[0].strip()
        m = _DEP_SPEC.match(name_part)
        if not m:
            continue
        name, ver = m.group(1), m.group(2) or ""
        out[name] = ver
    return out


def _version_parts(version: str) -> list[int]:
    parts: list[int] = []
    for chunk in re.split(r"[.\-]", version)[:3]:
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return parts


def check_dependencies(requirements_text: str) -> list[DependencyFinding]:
    """تدقيق إصدارات معلن — إصابة تعني: إصدار أدنى من حد التنبيه."""
    deps = parse_dependencies(requirements_text)
    findings: list[DependencyFinding] = []
    for pkg, ver in deps.items():
        for adv in ADVISORIES:
            if pkg.lower() != adv.package.lower():
                continue
            if not ver:
                findings.append(DependencyFinding(pkg, ver, adv))
                continue
            if _version_parts(ver) < _version_parts(adv.affected_below):
                findings.append(DependencyFinding(pkg, ver, adv))
    return findings


# ── 3: حارس حقن المطالبات ─────────────────────────────────────────────────

#: إشارات الحقن المعلنة — عبارات تحاول توجيه النموذج من محتوى غير موثوق.
INJECTION_SIGNALS: tuple[str, ...] = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "disregard previous",
    "you are now",
    "system prompt",
    "do not reveal",
    "forget your rules",
    "repeat the instructions",
    "override your",
    "jailbreak",
)


@dataclass(frozen=True)
class InjectionHit:
    """محاولة حقن مكتشفة — الملف والسطر والإشارة."""

    file: str
    line: int
    signal: str


class InjectionGuard:
    """حارِس الحقن — يكتشف ويحيّد ويغلّف محتوى المستودع بحد ثقة."""

    def scan(self, text: str, path: str = "<inline>") -> list[InjectionHit]:
        hits: list[InjectionHit] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for signal in INJECTION_SIGNALS:
                if signal in lowered:
                    hits.append(InjectionHit(file=path, line=line_no,
                                             signal=signal))
                    break
        return hits

    def neutralize(self, text: str) -> str:
        """تحييد سطور تشبه التوجيه ثم تغليف بحد ثقة معلن.

        المخرج يُدرج في مطالبات الوكلاء كما هو — ما داخله محتوى للقراءة
        لا تعليمات، والحد يعلن ذلك للنموذج نصًا صريحًا.
        """
        safe_lines: list[str] = []
        for line in text.splitlines():
            lowered = line.lower()
            if any(s in lowered for s in INJECTION_SIGNALS):
                safe_lines.append("[مُحيَّد: سطر يشبه تعليمة توجيه]")
            else:
                safe_lines.append(line)
        body = "\n".join(safe_lines)
        return (
            "<TRUST_BOUNDARY type='untrusted-repo-content'>\n"
            f"{body}\n"
            "</TRUST_BOUNDARY>\n"
        )


# ── 4: نموذج تهديد مصغّر للرقعة ───────────────────────────────────────────

#: أنماط نموذج التهديد — كل نمط خطر معلن بمبرر ودرجة.
THREAT_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("eval_exec", r"\beval\(|\bexec\(",
     "critical", "تنفيذ ديناميكي لسلاسل — رقعة لا تحتاجه مرفوضة"),
    ("shell_true", r"shell\s*=\s*True",
     "high", "استدعاء أمر بنظام مفكّك — حقن أوامر ممكن"),
    ("pickle_load", r"pickle\.loads?\(",
     "high", "فك تسلسل غير موثوق — تنفيذ كود عن بُعد"),
    ("bare_except", r"except\s*:",
     "medium", "استثناء عارٍ يبتلع أخطاء برمجية"),
    ("random_token", r"random\(\)\s*\+|uuid4\(\)\.hex\s*\+",
     "low", "مادة سرّية من مصدر غير مضمّن للأسرار"),
    ("http_plain", r"http://(?!localhost|127\.0\.0\.1)",
     "low", "نقل غير مشفّر لنقطة خارجية"),
)


@dataclass(frozen=True)
class ThreatHit:
    """قاعدة تهديد مطابقة — الفئة والخطورة والسطر."""

    rule: str
    severity: str
    reason: str
    file: str
    line: int


def threat_model_scan(text: str, path: str) -> list[ThreatHit]:
    """مسح نموذج تهديد على نص رقعة/ملف — قواعد معلنة بلا تخمين."""
    hits: list[ThreatHit] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule, pattern, severity, reason in THREAT_RULES:
            if re.search(pattern, line):
                hits.append(ThreatHit(rule=rule, severity=severity,
                                      reason=reason, file=path, line=line_no))
    return hits


def security_report(requirements_text: str = "",
                    texts: dict[str, str] | None = None,
                    guard: InjectionGuard | None = None) -> dict[str, Any]:
    """تقرير أمني موحّد حتمي — مدخل قسم الأمن إلى الأدلة والتقارير."""
    texts = texts or {}
    guard = guard or InjectionGuard()
    secret_hits: list[dict[str, str]] = [
        {"kind": h.kind, "file": h.file, "line": str(h.line),
         "snippet": h.snippet}
        for path, text in sorted(texts.items())
        for h in scan_text_for_secrets(text, path)
    ]
    dep_findings = check_dependencies(requirements_text) if requirements_text else []
    injection_hits: list[dict[str, str]] = [
        {"file": h.file, "line": str(h.line), "signal": h.signal}
        for path, text in sorted(texts.items())
        for h in guard.scan(text, path)
    ]
    threat_hits: list[dict[str, str]] = [
        {"rule": h.rule, "severity": h.severity, "file": h.file,
         "line": str(h.line), "reason": h.reason}
        for path, text in sorted(texts.items())
        for h in threat_model_scan(text, path)
    ]
    return {
        "secrets": secret_hits,
        "dependencies": [
            {"package": f.package, "version": f.version,
             "cve": f.advisory.cve, "severity": f.advisory.severity,
             "summary": f.advisory.summary}
            for f in dep_findings
        ],
        "injections": injection_hits,
        "threat_model": threat_hits,
        "counts": {
            "secrets": len(secret_hits),
            "vulnerable_dependencies": len(dep_findings),
            "injections": len(injection_hits),
            "threat_hits": len(threat_hits),
        },
    }
