"""Framework — واجهة موحدة لتوليد الأنظمة.

الاستخدام:
    from hive.generators.framework import generate_system
    
    result = generate_system(
        spec={"name": "todo_api", "entities": [...]},
        output_dir="/public/generated/todo_api",
    )
    # result = {
    #   "success": True,
    #   "name": "todo_api",
    #   "output_dir": "...",
    #   "files_count": 9,
    #   "files": [...],
    #   "verify_passed": True,
    #   "verify_report": {...},
    # }
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import traceback

from hive.generators.ir import build_ir, IRValidationError
from hive.generators.generators.backend_generator import BackendGenerator
from hive.generators.composer import Composer
from hive.generators.verifier import verify_system, format_report


def generate_system(
    spec: Dict[str, Any],
    output_dir: str | Path,
    blueprint: str = "api_backend",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """يولّد نظامًا كاملًا من spec.

    Args:
        spec: وصف النظام (name, entities, endpoints, ...)
        output_dir: مكان الكتابة
        blueprint: نوع المولّد (حاليًا api_backend فقط)
        dry_run: لا تكتب، فقط ارجع الملفات

    Returns:
        dict مع success/error/files/verify
    """
    result = {
        "success": False,
        "name": spec.get("name", "unnamed"),
        "blueprint": blueprint,
        "output_dir": str(output_dir),
        "files_count": 0,
        "files": [],
        "verify_passed": False,
        "verify_report": None,
        "error": None,
    }

    # 1. spec → IR
    try:
        ir = build_ir(spec)
    except IRValidationError as e:
        result["error"] = f"IR validation: {'; '.join(e.errors)}"
        return result
    except Exception as e:
        result["error"] = f"IR build: {type(e).__name__}: {e}"
        return result

    # 2. IR → generators
    try:
        generators = []
        if blueprint in ("api_backend", "backend", "full_stack"):
            generators.append(BackendGenerator())
        else:
            result["error"] = f"blueprint غير معروف: {blueprint}"
            return result
    except Exception as e:
        result["error"] = f"generator init: {type(e).__name__}: {e}"
        return result

    # 3. تشغيل المولّدات
    parts = []
    for gen in generators:
        if not gen.can_handle(ir):
            result["error"] = f"{gen.name} لا يستطيع التعامل مع IR"
            return result
        try:
            parts.append(gen.generate(ir, Path(output_dir)))
        except Exception as e:
            result["error"] = f"{gen.name} generate: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            return result

    # 4. compose
    try:
        composer = Composer(Path(output_dir))
        compose_result = composer.compose(parts, dry_run=dry_run)
        result["files"] = compose_result.get("written", compose_result.get("would_write", []))
        result["files_count"] = len(result["files"])
    except Exception as e:
        result["error"] = f"compose: {type(e).__name__}: {e}"
        return result

    if dry_run:
        result["success"] = True
        return result

    # 5. verify
    try:
        report = verify_system(Path(output_dir))
        result["verify_passed"] = report.passed
        result["verify_report"] = {
            "passed": report.passed,
            "checks_count": len(report.checks),
            "checks_ok": sum(1 for c in report.checks if c.ok),
            "errors": report.errors,
            "warnings": report.warnings,
        }
    except Exception as e:
        result["error"] = f"verify: {type(e).__name__}: {e}"
        return result

    result["success"] = True
    return result


def format_result(result: Dict[str, Any]) -> str:
    """تنسيق النتيجة لـ Telegram (Markdown)."""
    if not result["success"]:
        return (
            f"❌ *فشل التوليد*\n"
            f"النظام: `{result['name']}`\n"
            f"الخطأ: `{result.get('error', 'unknown')[:300]}`"
        )

    lines = [
        f"✅ *تم توليد النظام*",
        f"",
        f"📦 *{result['name']}*",
        f"الملفات: {result['files_count']}",
        f"المجلد: `{result['output_dir']}`",
        f"",
    ]

    vr = result.get("verify_report") or {}
    if vr:
        status = "✅ PASSED" if vr.get("passed") else "❌ FAILED"
        lines.append(f"🔍 *Verify:* {status}")
        lines.append(f"  Checks: {vr.get('checks_ok', 0)}/{vr.get('checks_count', 0)}")
        if vr.get("errors"):
            for e in vr["errors"][:3]:
                lines.append(f"  ⚠️ {e[:100]}")

    if result["files"]:
        lines.append("")
        lines.append("*الملفات:*")
        for f in result["files"][:12]:
            lines.append(f"  • `{f}`")
        if len(result["files"]) > 12:
            lines.append(f"  ... +{len(result['files']) - 12}")

    return "\n".join(lines)
