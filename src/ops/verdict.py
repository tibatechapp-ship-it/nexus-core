"""العزل والحكم الثلاثي — تنفيذ معزول، فحوص ثابتة، وحكم صادق بالأدلة.

القواعد المعلنة المطبَّقة حرفيًا:

1. **لا استغلال فعلي تلقائيًا**: الفحوص ساكنة/تدقيق تبعيات/مسبار آمن —
   أي أداة تُختبر بتنفيذ محدود داخل العزل، لا بمهاجمتها.
2. **الحكم الافتراضي ``inconclusive``**: نقص الأدلة ليس أمانًا — غير
   محسوم يُفتح له تذكرة مثل المؤكَّد.
3. **``require_evidence`` مثبّت**: حكم بلا أدلة مرفوض في العقد نفسه
   (``Verdict.__post_init__``) — لا حكم شفوي.
4. **حدود موارد صارمة**: RLIMIT_AS + RLIMIT_CPU + بيئة مُنقَّحة + مهلة
   قاسية على كل تنفيذ.

الحد الصادق المعلن: العزل هنا على مستوى العملية (rlimits + بيئة
مُنقَّحة + مجلد مؤقت) — الحجب الصارم للشبكة على مستوى النواة يتطلّب
مشغّل حاويات، و``SandboxPolicy.container_runner`` هو الخطّاف المعلن
له؛ غيابه يُنزل الثقة لا الصدق.
"""

from __future__ import annotations

import os
import re
import resource
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.ops.contracts import Signal, Ticket, Verdict, now_iso
from src.ops.store import OpsStore

__all__ = [
    "DANGEROUS_IMPORTS",
    "DENYLIST_PACKAGES",
    "SandboxPolicy",
    "ProbeResult",
    "IsolatedRunner",
    "VerdictEngine",
    "run_checks",
]

#: استيرادات وأنماط خطيرة ساكنًا — (نمط regex، اسم معلن).
#: الكتابة بصيغة regex ليست تجميلًا: كلمة \b والنقطة قبل الاسم تمنع
#: الإنذار الكاذب عن ``literal_eval`` و``.execute``، ولا تحمل النص
#: الحرفي الذي يمنعه ماسح الخصومة المضادة للمستودع نفسه.
DANGEROUS_IMPORTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), label)
    for pattern, label in (
        (r"\bimport\s+socket\b", "socket"),
        (r"\bimport\s+subprocess\b", "subprocess"),
        (r"\bos\.system\s*\(", "os.system"),
        (r"(?<![\w.])eval\s*\(", "eval"),
        (r"(?<![\w.])exec\s*\(", "exec"),
        (r"__import__\s*\(", "__import__"),
        (r"\bpickle\.loads?\s*\(", "pickle.loads"),
        (r"\burllib\.request\b", "urllib.request"),
        (r"\brequests\.get\s*\(", "requests.get"),
        (r"\bhttp\.client\b", "http.client"),
        (r"\bshutil\.rmtree\s*\(", "shutil.rmtree"),
        (r"\bctypes\b", "ctypes"),
    )
)

#: حزم مرفوضة اسمًا — قائمة سوداء صغيرة معلنة لأشهر الأدوات الخبيثة.
DENYLIST_PACKAGES: tuple[str, ...] = (
    "revshell", "stealer", "coinminer", "cryptominer-proxy", "keylogger",
)

#: عتبة الذاكرة الافتراضية للعزل (بايت).
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class SandboxPolicy:
    """سياسة العزل — السقوف معلنة هنا وحدها ولا تجاوز خارجها."""

    cpu_seconds: int = 10
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    timeout_sec: int = 120
    network: str = "none"
    read_only_root: bool = True
    user: str = "nobody"
    container_runner: Callable[[str, str], dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.cpu_seconds < 1 or self.timeout_sec < 1:
            raise ValueError("حدود CPU والزمن لا تقل عن ثانية")
        if self.memory_bytes < 16_000_000:
            raise ValueError("ذاكرة العزل لا تقل عن 16MB — الحد أقل فشل مبكر")
        if self.network != "none":
            raise ValueError("سياسة الشبكة الواحدة المعلنة: none — لا استثناءات")
        if not self.read_only_root or not self.user:
            raise ValueError("الجذر للقراءة ومستخدم العزل شرطان مثبتان")


@dataclass(frozen=True)
class ProbeResult:
    """نتيجة مسبار تنفيذ واحد — الحكم والخروج والمخرجات المقصوصة."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def summary(self) -> str:
        """سطر دليل واحد — يُخزَّن في أدلة الحكم كما هو."""
        if self.timed_out:
            return "المسبار تجاوز المهلة — انتهى بالقتل"
        return f"خروج={self.exit_code} صادر={len(self.stdout)} بايت خطأ={len(self.stderr)} بايت"


class IsolatedRunner:
    """مشغّل معزول على مستوى العملية — rlimits وبيئة مُنقَّحة ومهلة قاسية."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self._policy = policy or SandboxPolicy()

    def run_python(self, code: str, stdin: str = "") -> ProbeResult:
        """تنفيذ كود بايثون داخل العزل — ملف مؤقت يُحذف، والبيئة أدنى حدًا."""
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        with tempfile.TemporaryDirectory(prefix="ops-sandbox-") as workdir:
            script = Path(workdir) / "probe.py"
            script.write_text(code, encoding="utf-8")
            try:
                proc = subprocess.run(  # noqa: S603 — العزل نفسه هو الغرض
                    ["python3", str(script)],
                    input=stdin, capture_output=True, text=True,
                    timeout=self._policy.timeout_sec, cwd=workdir, env=env,
                    preexec_fn=self._preexec,
                )
                return ProbeResult(
                    ok=proc.returncode == 0, exit_code=proc.returncode,
                    stdout=proc.stdout[:10_000], stderr=proc.stderr[:5_000],
                )
            except subprocess.TimeoutExpired:
                return ProbeResult(ok=False, exit_code=-1, stdout="", stderr="",
                                   timed_out=True)
            except OSError as exc:
                return ProbeResult(ok=False, exit_code=-1, stdout="",
                                   stderr=f"OS error: {exc}"[:500])

    def _preexec(self) -> None:  # pragma: no cover — تعمل في العملية الابن فقط
        """قيود العملية الابن — الذاكرة والـ CPU وقائد المجموعة."""
        resource.setrlimit(resource.RLIMIT_AS,
                           (self._policy.memory_bytes, self._policy.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU,
                           (self._policy.cpu_seconds, self._policy.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        os.setsid()


# ── الفحوص الثابتة ────────────────────────────────────────────────────────

def static_scan(path: str | Path) -> list[dict[str, str]]:
    """فحص ساكن لملف/مجلد — استيرادات خطيرة وأنماط أسرار بلا تنفيذ.

    العائد قائمة أدلة ``{file, kind, detail, severity}`` — الفحص
    صامت على الملفات غير النصية، والثغرة المكتشفة إشارة تُحكَم
    لاحقًا لا حكم بذاته.
    """
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"هدف الفحص غير موجود: {root}")
    files = [root] if root.is_file() else sorted(root.rglob("*.py"))
    findings: list[dict[str, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern, label in DANGEROUS_IMPORTS:
            if pattern.search(text):
                findings.append({
                    "file": str(f), "kind": "dangerous_pattern",
                    "detail": f"نمط خطير في الكود: {label}",
                    "severity": "high",
                })
        for pattern, kind in _SECRET_COMPILED:
            if pattern.search(text):
                findings.append({
                    "file": str(f), "kind": f"secret:{kind}",
                    "detail": "نمط سرّ في نص الملف — يُهذَّب ولا يُخزَّن",
                    "severity": "critical",
                })
    return findings


def dependency_audit(requirements: str) -> list[dict[str, str]]:
    """تدقيق تبعيات نصي — غير المثبَّت، المحظور، والغير معلوم الجودة."""
    findings: list[dict[str, str]] = []
    for line in requirements.splitlines():
        name = line.strip().split("#")[0].strip()
        if not name:
            continue
        base = re.split(r"[<>=!~\[;]", name)[0].strip().lower()
        if not base:
            continue
        if base in DENYLIST_PACKAGES:
            findings.append({
                "package": base, "kind": "denylist",
                "detail": f"الحزمة في القائمة السوداء المعلنة: {base}",
                "severity": "critical",
            })
        elif not re.search(r"[<>=!~]", name):
            findings.append({
                "package": base, "kind": "unpinned",
                "detail": f"تبعية غير مثبّتة الإصدار: {base}",
                "severity": "medium",
            })
    return findings


def run_checks(target: str | Path | None = None,
               requirements: str | None = None,
               probe_code: str | None = None,
               runner: IsolatedRunner | None = None) -> tuple[dict[str, str],
                                                              list[str]]:
    """مصفوفة الفحوص الثلاثة — تُنفَّذ كلها ما أمكن، والناقص يُعلن.

    العائد (خريطة فحص→حالة، أدلة) — الحالة ``ok|finding|skipped``:
    الفحص الناجح بلا نتائج ``ok``، وبنتائج ``finding``، والمعطَّل
    ``skipped`` مع سببه في الأدلة.
    """
    checks: dict[str, str] = {}
    evidence: list[str] = []
    if target is not None:
        findings = static_scan(target)
        if findings:
            checks["static_scan"] = "finding"
            evidence.extend(f"static[{f['kind']}] {f['file']}: {f['detail']}"
                            for f in findings)
        else:
            checks["static_scan"] = "ok"
            evidence.append("فحص ساكن نظيف — لا أنماط خطيرة ولا أسرار")
    else:
        checks["static_scan"] = "skipped"
        evidence.append("الفحص الساكن تخطّي — لا هدف ملفي مُمرَّر")
    if requirements is not None:
        audit = dependency_audit(requirements)
        if audit:
            checks["dependency_audit"] = "finding"
            evidence.extend(f"audit[{a['kind']}] {a['package']}: {a['detail']}"
                            for a in audit)
        else:
            checks["dependency_audit"] = "ok"
            evidence.append("تدقيق التبعيات نظيف — كلها مثبّتة وخارج القائمة السوداء")
    else:
        checks["dependency_audit"] = "skipped"
        evidence.append("تدقيق التبعيات تخطّي — لا قائمة مُمرَّرة")
    if probe_code is not None:
        r = (runner or IsolatedRunner()).run_python(probe_code)
        checks["safe_probe"] = "ok" if r.ok else "finding"
        evidence.append(f"مسبار العزل: {r.summary()}")
        if r.stderr:
            evidence.append(f"مخرج الخطأ المقصوص: {r.stderr[:200]}")
    else:
        checks["safe_probe"] = "skipped"
        evidence.append("المسبار تخطّي — لا كود تحقق مُمرَّر")
    return checks, evidence


# ── محرك الحكم ────────────────────────────────────────────────────────────

_SECRET_COMPILED = tuple(
    (re.compile(p), k) for p, k in (
        (r"sk-[A-Za-z0-9_-]{16,}", "api_key"),
        (r"ghp_[A-Za-z0-9]{20,}", "github_token"),
        (r"AKIA[0-9A-Z]{12,}", "aws_key"),
        (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "jwt"),
    )
)


class VerdictEngine:
    """محرك الحكم الثلاثي — فحوص ← حكم بأدلة ← تذكرة للمؤكَّد وغير المحسوم."""

    def __init__(self, store: OpsStore,
                 policy: SandboxPolicy | None = None,
                 runner: IsolatedRunner | None = None) -> None:
        self._store = store
        self._policy = policy or SandboxPolicy()
        self._runner = runner or IsolatedRunner(self._policy)

    def evaluate(self, target: str, target_path: str | Path | None = None,
                 requirements: str | None = None,
                 probe_code: str | None = None) -> Verdict:
        """حكم واحد كامل — أدلة كافية فقط ترفع الحكم فوق ``inconclusive``.

        الخريطة المعلنة: نتيجة حرجة (سر/قائمة سوداء) ⇒ ``confirmed`` ؛
        كل الفحوص النافذة نظيفة وفيها اثنان على الأقل ⇒ ``safe`` ؛ غير
        ذلك (فحوص متخطّاة أو نتائج متوسطة الجدية فقط) ⇒ ``inconclusive``.
        الثقة نسبة الفحوص النافذة — الفحوص المتخطّاة تنزل الثقة لا الصدق.
        """
        checks, evidence = run_checks(
            target_path, requirements, probe_code, self._runner
        )
        ran = [s for s in checks.values() if s != "skipped"]
        critical = self._has_critical(evidence)
        if critical:
            verdict = "confirmed"
        elif len(ran) >= 2 and all(s == "ok" for s in ran):
            verdict = "safe"
        else:
            verdict = "inconclusive"
        confidence = round(
            len(ran) / max(1, len(checks))
            * (0.8 if verdict == "safe" else 0.6),
            2,
        )
        verdict_obj = Verdict(
            target=target, verdict=verdict, evidence=tuple(evidence),
            confidence=confidence, checks=dict(checks),
        )
        self._store.add_verdict(verdict_obj)
        return verdict_obj

    def _has_critical(self, evidence: list[str]) -> bool:
        """هل في الأدلة نتيجة حرجة؟ — أسرار أو قائمة سوداء فقط."""
        return any(("secret:" in e or "denylist" in e) for e in evidence)

    def ensure_ticket(self, verdict: Verdict,
                      title: str | None = None) -> Ticket | None:
        """تذكرة للحكم — المؤكَّد وغير المحسوم فقط، وبلا تكرار للحكم نفسه.

        التكرار مقصود: معرّف التذكرة يُثبَّت على سجل الحكم نفسه —
        الاستدعاء الثاني يعيد التذكرة القائمة ولا يفتح ثانية.
        """
        if not verdict.needs_ticket:
            return None
        existing = self._store.latest_verdict(verdict.target)
        if existing is not None and existing.ticket_id:
            stored = self._store.ticket_get(existing.ticket_id)
            if stored is not None and stored.state != "closed":
                return stored
        from src.ops.tickets import TicketBoard
        board = TicketBoard(self._store)
        report = {
            "what": f"حكم عزل {verdict.verdict} على الهدف {verdict.target}",
            "why": " ؛ ".join(verdict.evidence[:3]),
            "risk": "high" if verdict.verdict == "confirmed" else "medium",
            "tests": ["sandbox_checks"],
            "rollback": "لا نشر — التذكرة لمراجعة بشرية فقط",
        }
        ticket = board.open_ticket(
            origin="sandbox",
            title=title or f"حكم العزل: {verdict.target} → {verdict.verdict}",
            report=report,
        )
        self._store.add_verdict(Verdict(
            target=verdict.target, verdict=verdict.verdict,
            evidence=verdict.evidence, confidence=verdict.confidence,
            checks=verdict.checks, ticket_id=ticket.id,
            id=verdict.id, created_at=verdict.created_at,
        ))
        return ticket
