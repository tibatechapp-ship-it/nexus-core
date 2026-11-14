"""اختبارات العزل والحكم الثلاثي — الفحوص والأدلة والتذاكر الآلية."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ops import OpsStore
from src.ops.verdict import (
    DENYLIST_PACKAGES,
    DANGEROUS_IMPORTS,
    IsolatedRunner,
    ProbeResult,
    SandboxPolicy,
    VerdictEngine,
    dependency_audit,
    run_checks,
    static_scan,
)


class TestSandboxPolicy:
    def test_defaults_declared(self) -> None:
        """الافتراضات المعلنة: شبكة none وجذر للقراءة ومستخدم معلن."""
        policy = SandboxPolicy()
        assert policy.network == "none" and policy.read_only_root
        assert policy.user == "nobody" and policy.container_runner is None

    def test_invalid_bounds_rejected(self) -> None:
        """كل سقف خارج مداه رفع — السياسة لا تُتداول على تخمين."""
        with pytest.raises(ValueError, match="ثانية"):
            SandboxPolicy(cpu_seconds=0)
        with pytest.raises(ValueError, match="ثانية"):
            SandboxPolicy(timeout_sec=0)
        with pytest.raises(ValueError, match="ذاكرة"):
            SandboxPolicy(memory_bytes=1_000)
        with pytest.raises(ValueError, match="الشبكة"):
            SandboxPolicy(network="open")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="الجذر"):
            SandboxPolicy(read_only_root=False)
        with pytest.raises(ValueError, match="مستخدم"):
            SandboxPolicy(user="")


class TestIsolatedRunner:
    def test_clean_probe_succeeds(self) -> None:
        """مسبار نظيف يعيد خروج صفر ومخرجاته — العزل لا يعاقب السليم."""
        r = IsolatedRunner().run_python("print('سليم')")
        assert r.ok and r.exit_code == 0 and "سليم" in r.stdout

    def test_failing_probe_captured(self) -> None:
        """الخطأ يُلتقط بالمخرجات ورمز الخروج — الدليل كامل."""
        r = IsolatedRunner().run_python("raise ValueError('انفجار')")
        assert not r.ok and "انفجار" in r.stderr and r.exit_code != 0

    def test_summary_line_honest(self) -> None:
        """سطر الملخص يذكر الخروج — والمهلة تُذكر بلا تلفيف."""
        ok = ProbeResult(ok=True, exit_code=0, stdout="abc", stderr="")
        assert "خروج=0" in ok.summary()
        killed = ProbeResult(ok=False, exit_code=-1, stdout="", stderr="",
                             timed_out=True)
        assert "المهلة" in killed.summary()

    def test_memory_limit_enforced(self) -> None:
        """سقف الذاكرة مفروض فعليًا — طلب ضخم يفشل بدل أن يقتل المضيف."""
        policy = SandboxPolicy(memory_bytes=32_000_000, cpu_seconds=5,
                               timeout_sec=10)
        r = IsolatedRunner(policy).run_python("x = bytearray(200_000_000)")
        assert not r.ok

    def test_cpu_limit_enforced(self) -> None:
        """سقف CPU مفروض فعليًا — الحلقة اللانهائية تنتهي بالحكم لا بالقتل."""
        policy = SandboxPolicy(cpu_seconds=1, timeout_sec=15)
        r = IsolatedRunner(policy).run_python("while True: pass")
        assert not r.ok

    def test_environment_scrubbed(self) -> None:
        """البيئة مُنقَّحة — لا متغيرات مضيف تسرب إلى العزل."""
        r = IsolatedRunner().run_python(
            "import os; print('TOKEN' in ''.join(os.environ.keys()))"
        )
        assert "False" in r.stdout


class TestStaticScan:
    def test_secret_and_dangerous_findings(self, tmp_path: Path) -> None:
        """الأسرار والأنماط الخطيرة تُكتشف بلا تنفيذ — إشارات لا أحكام."""
        f = tmp_path / "suspicious.py"
        f.write_text("import socket\nK = 'ghp_" + "a" * 30 + "'", encoding="utf-8")
        findings = static_scan(f)
        kinds = {x["kind"] for x in findings}
        assert "dangerous_pattern" in kinds and any(
            k.startswith("secret:") for k in kinds
        )
        assert all(x["severity"] in {"high", "critical"} for x in findings)

    def test_clean_file_no_findings(self, tmp_path: Path) -> None:
        """الملف السليم صفر نتائج — الفحص لا يصنع ضجيجًا."""
        f = tmp_path / "clean.py"
        f.write_text("def add(a: int, b: int) -> int:\n    return a + b\n",
                     encoding="utf-8")
        assert static_scan(f) == []

    def test_directory_scans_py_files_only(self, tmp_path: Path) -> None:
        """المجلد يفحص ``*.py`` فقط — النصوص الأخرى ليست هدف الفحص."""
        (tmp_path / "a.py").write_text("exec(input())", encoding="utf-8")
        (tmp_path / "b.txt").write_text("exec(input())", encoding="utf-8")
        findings = static_scan(tmp_path)
        assert findings and all(f["file"].endswith(".py") for f in findings)

    def test_missing_target_raises(self, tmp_path: Path) -> None:
        """هدف غائب رفع صريح — لا فحص على خيال."""
        with pytest.raises(FileNotFoundError):
            static_scan(tmp_path / "ghost")


class TestDependencyAudit:
    def test_unpinned_and_denylist(self) -> None:
        """غير المثبّت مُعلَّم medium والمحظور critical — الجدية صادقة."""
        findings = dependency_audit("requests\nflask==2.0\nrevshell==1")
        kinds = {f["package"]: f["kind"] for f in findings}
        assert kinds == {"requests": "unpinned", "revshell": "denylist"}

    def test_comments_and_empty_lines_ignored(self) -> None:
        """التعليقات والفراغات لا تدخل التدقيق — لا ضجيج."""
        assert dependency_audit("# تعليق\n\n  \nrequests==2.0") == []

    def test_denylist_declared(self) -> None:
        """القائمة السوداء معلنة وغير فارغة — بيان قابل للفحص."""
        assert len(DENYLIST_PACKAGES) >= 3 and len(DANGEROUS_IMPORTS) >= 8


class TestRunChecks:
    def test_all_three_checks_run(self, tmp_path: Path) -> None:
        """المصفوفة الكاملة: ساكن + تدقيق + مسبار — كلها لها حالة."""
        checks, evidence = run_checks(
            tmp_path, "requests==2.0", "print('p')", IsolatedRunner()
        )
        assert set(checks) == {"static_scan", "dependency_audit", "safe_probe"}
        assert checks["static_scan"] == "ok"
        assert checks["dependency_audit"] == "ok"
        assert checks["safe_probe"] == "ok"
        assert len(evidence) >= 3

    def test_skipped_checks_declared_with_reason(self) -> None:
        """الفحص المعطّل يُعلن في الأدلة — لا صمت ولا تقدير."""
        checks, evidence = run_checks(None, None, None, None)
        assert checks == {"static_scan": "skipped",
                          "dependency_audit": "skipped",
                          "safe_probe": "skipped"}
        assert len(evidence) == 3 and all("تخطّي" in e for e in evidence)

    def test_probe_failure_recorded_as_finding(self, tmp_path: Path) -> None:
        """المسبار الفاشل finding مع مخرج الخطأ المقصوص في الأدلة."""
        checks, evidence = run_checks(tmp_path, "requests==2.0",
                                      "raise RuntimeError('بووم')",
                                      IsolatedRunner())
        assert checks["safe_probe"] == "finding"
        assert any("بووم" in e for e in evidence)


class TestVerdictEngine:
    @pytest.fixture()
    def engine(self) -> VerdictEngine:
        """محرك على مخزن ذاكرة — سياسة مختصرة لسرعة الاختبار."""
        return VerdictEngine(OpsStore(":memory:"),
                             SandboxPolicy(cpu_seconds=5, timeout_sec=15))

    def test_critical_secret_confirmed(self, engine: VerdictEngine,
                                       tmp_path: Path) -> None:
        """سر مكشوف ⇒ مؤكَّد بأدلة وتذكرة آلية مرتبطة."""
        f = tmp_path / "leak.py"
        f.write_text("K='ghp_" + "a" * 30 + "'", encoding="utf-8")
        v = engine.evaluate("leak@1", target_path=f)
        assert v.verdict == "confirmed" and v.needs_ticket
        ticket = engine.ensure_ticket(v)
        assert ticket is not None and ticket.origin == "sandbox"
        assert ticket.report["risk"] == "high"
        assert engine._store.latest_verdict("leak@1").ticket_id == ticket.id  # type: ignore[union-attr]

    def test_denylist_package_confirmed(self, engine: VerdictEngine) -> None:
        """حزمة القائمة السوداء ⇒ مؤكَّد حتى بلا ملفات."""
        v = engine.evaluate("evil@1", requirements="cryptominer-proxy==1")
        assert v.verdict == "confirmed"

    def test_clean_full_matrix_safe(self, engine: VerdictEngine,
                                    tmp_path: Path) -> None:
        """فحوص نافذة نظيفة اثنان فأكثر ⇒ آمن ولا تذكرة."""
        v = engine.evaluate("good@1", target_path=tmp_path,
                            requirements="x==1", probe_code="print(1)")
        assert v.verdict == "safe" and not v.needs_ticket
        assert engine.ensure_ticket(v) is None

    def test_partial_matrix_inconclusive(self, engine: VerdictEngine) -> None:
        """فحص واحد نافذ نظيف ⇒ غير محسوم — نقص الأدلة ليس أمانًا."""
        v = engine.evaluate("partial@1", requirements="x==1")
        assert v.verdict == "inconclusive" and v.needs_ticket
        t = engine.ensure_ticket(v)
        assert t is not None and t.report["risk"] == "medium"

    def test_medium_finding_only_inconclusive(self, engine: VerdictEngine) -> None:
        """نتيجة متوسطة وحدها (تبعية غير مثبّتة) ⇒ غير محسوم لا مؤكَّد."""
        v = engine.evaluate("medium@1", requirements="loose-thing")
        assert v.verdict == "inconclusive"

    def test_ensure_ticket_idempotent(self, engine: VerdictEngine,
                                      tmp_path: Path) -> None:
        """استدعاء التذكرة مرتين يعيد نفسها — لا تكرار تذاكر."""
        f = tmp_path / "l2.py"
        f.write_text("K='ghp_" + "a" * 30 + "'", encoding="utf-8")
        v = engine.evaluate("idem@1", target_path=f)
        t1 = engine.ensure_ticket(v)
        t2 = engine.ensure_ticket(v)
        assert t1 is not None and t2 is not None and t1.id == t2.id

    def test_confidence_scales_with_ran_checks(self, engine: VerdictEngine) -> None:
        """الثقة نسبة الفحوص النافذة — المتخطّاة تنزلها لا ترفعها."""
        full = engine.evaluate("c1@1", target_path=".", requirements="x==1",
                               probe_code="print(1)")
        partial = engine.evaluate("c2@1", requirements="x==1")
        assert full.confidence > partial.confidence
