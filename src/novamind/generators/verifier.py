"""System Verifier — يتحقق من النظام المُولَّد."""
from __future__ import annotations
from pathlib import Path
from typing import List
import py_compile
import json

from hive.generators.contract import VerifyReport


def verify_system(system_dir: Path) -> VerifyReport:
    system_dir = Path(system_dir)
    report = VerifyReport(passed=True)

    if not system_dir.exists():
        report.add_check("system_dir_exists", False, str(system_dir))
        return report

    report.add_check("system_dir_exists", True)

    # 1. Python compile
    py_files = sorted(system_dir.rglob("*.py"))
    report.add_check("has_python_files", len(py_files) > 0, f"{len(py_files)} files")

    compiled = 0
    failed = []
    for py in py_files:
        try:
            py_compile.compile(str(py), doraise=True)
            compiled += 1
        except py_compile.PyCompileError as e:
            failed.append(str(py.relative_to(system_dir)))

    report.add_check("all_python_compiles", len(failed) == 0,
                     f"{compiled}/{len(py_files)} ok" if not failed else f"failed: {failed}")

    # 2. manifest موجود
    manifest_path = system_dir / ".novamind_manifest.json"
    if manifest_path.exists():
        report.add_check("manifest_exists", True)
        try:
            m = json.loads(manifest_path.read_text())
            report.add_check("manifest_valid", "files" in m, f"{len(m.get('files', {}))} files")
        except Exception as e:
            report.add_check("manifest_valid", False, str(e))
    else:
        report.add_check("manifest_exists", False)

    # 3. لا ملفات فارغة (باستثناء __init__)
    empty = [p for p in py_files
             if p.name != "__init__.py" and p.stat().st_size == 0]
    report.add_check("no_empty_files", len(empty) == 0,
                     f"empty: {[str(p.relative_to(system_dir)) for p in empty]}" if empty else "")

    # 4. requirements.txt موجود
    report.add_check("has_requirements", (system_dir / "requirements.txt").exists())

    # 5. README موجود
    report.add_check("has_readme", (system_dir / "README.md").exists())

    return report


def format_report(report: VerifyReport, system_dir: Path) -> str:
    lines = []
    status = "✅ PASSED" if report.passed else "❌ FAILED"
    lines.append(f"{status} — Verify Report")
    lines.append(f"  Dir: {system_dir}")
    lines.append(f"  Checks: {len(report.checks)} ({sum(1 for c in report.checks if c.ok)} ok)")
    if report.errors:
        lines.append("  Errors:")
        for e in report.errors:
            lines.append(f"    • {e}")
    if report.warnings:
        lines.append("  Warnings:")
        for w in report.warnings:
            lines.append(f"    • {w}")
    return "\n".join(lines)
