"""Quality Gate v2 — تقييم نتائج pipeline بقواعد قابلة للتخصيص."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class QualityGateResult:
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "warnings": self.warnings,
            "score": self.score,
            "details": self.details,
        }


def evaluate_pipeline_result(
    pipeline_id: str,
    results: Dict[str, Any],
    gates: Optional[Dict[str, Any]] = None,
) -> QualityGateResult:
    """تقييم نتيجة pipeline.

    Args:
        pipeline_id: اسم pipeline
        results: النتيجة الكاملة من run_pipeline
        gates: قواعد مخصصة (إن لم تُعطَ، تُستخدم gates من pipeline)

    Returns:
        QualityGateResult
    """
    if gates is None:
        from hive.orchestration.pipelines import get_pipeline
        pipeline = get_pipeline(pipeline_id)
        gates = (pipeline or {}).get("quality_gates", {})

    violations: List[str] = []
    warnings: List[str] = []
    details: Dict[str, Any] = {}

    # ── 1. فحص الحالة العامة ─────────────────────────────
    status = results.get("status")
    if status != "done":
        violations.append(f"pipeline_status={status}")
    details["pipeline_status"] = status

    # ── 2. فحص المراحل ───────────────────────────────────
    stages = results.get("stages", [])
    failed_stages = []
    for stage in stages:
        stage_name = stage.get("stage")
        for res in stage.get("results", []):
            if not res.get("success"):
                failed_stages.append(f"{stage_name}/{res.get('agent')}")
    details["failed_stages"] = failed_stages
    if failed_stages:
        warnings.append(f"{len(failed_stages)} agent(s) failed: {failed_stages[:3]}")

    # ── 3. فحص الـ security ─────────────────────────────
    if gates.get("require_security_pass"):
        security_failed = any(
            "security" in str(f).lower()
            for f in failed_stages
        )
        details["security_pass"] = not security_failed
        if security_failed:
            violations.append("security gate failed")

    # ── 4. فحص الـ tests ─────────────────────────────────
    if gates.get("require_tests_pass"):
        test_failed = any(
            "tester" in str(f).lower() or "test_generator" in str(f).lower()
            for f in failed_stages
        )
        details["tests_pass"] = not test_failed
        if test_failed:
            violations.append("tests gate failed")

    # ── 5. فحص human approval ───────────────────────────
    if gates.get("require_human_approval"):
        details["requires_approval"] = True
        warnings.append("deploy pipeline: human approval required before proceeding")

    # ── 6. حساب score ────────────────────────────────────
    score = 100.0
    score -= len(violations) * 30
    score -= len(warnings) * 5
    score = max(0.0, min(100.0, score))
    details["computed_score"] = score

    passed = len(violations) == 0

    return QualityGateResult(
        passed=passed,
        violations=violations,
        warnings=warnings,
        score=score,
        details=details,
    )


def evaluate_findings_gate(
    findings: List[Dict[str, Any]],
    max_high: int = 0,
    max_medium: int = 5,
) -> QualityGateResult:
    """فحص findings من review_engine.

    Args:
        findings: قائمة findings {severity, message, ...}
        max_high: أقصى عدد high مسموح
        max_medium: أقصى عدد medium مسموح
    """
    violations: List[str] = []
    warnings: List[str] = []

    by_sev: Dict[str, int] = {}
    for f in findings or []:
        sev = (f.get("severity") or "info").lower()
        by_sev[sev] = by_sev.get(sev, 0) + 1

    high_count = by_sev.get("high", 0)
    medium_count = by_sev.get("medium", 0)
    critical_count = by_sev.get("critical", 0)

    if critical_count > 0:
        violations.append(f"{critical_count} critical issues found")
    if high_count > max_high:
        violations.append(f"{high_count} high issues > max {max_high}")
    if medium_count > max_medium:
        warnings.append(f"{medium_count} medium issues > max {max_medium}")

    score = 100.0
    score -= critical_count * 40
    score -= high_count * 20
    score -= medium_count * 5
    score = max(0.0, min(100.0, score))

    return QualityGateResult(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
        score=score,
        details={"by_severity": by_sev},
    )


def format_gate_result(result: QualityGateResult) -> str:
    """تنسيق النتيجة للنشر."""
    lines = []
    icon = "✅" if result.passed else "❌"
    lines.append(f"{icon} *Quality Gate: {'PASSED' if result.passed else 'FAILED'}*")
    lines.append(f"Score: {result.score:.1f}/100")

    if result.violations:
        lines.append("")
        lines.append("🚫 *Violations:*")
        for v in result.violations:
            lines.append(f"  • {v}")

    if result.warnings:
        lines.append("")
        lines.append("⚠️ *Warnings:*")
        for w in result.warnings:
            lines.append(f"  • {w}")

    return "\n".join(lines)
