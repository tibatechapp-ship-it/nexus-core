"""
CleanupAgent — حذف الملفات المؤقتة بأمان
=============================================
يحذف فقط الملفات المؤقتة المعروفة (whitelist).

القواعد:
✅ Whitelist فقط — لا حذف تخميني
✅ dry_run افتراضي (آمن)
✅ لا يلمس الملفات الأساسية
✅ تقرير مفصّل

يحذف:
- __pycache__/, *.pyc, *.pyo
- .pytest_cache/, .mypy_cache/, .ruff_cache/
- *.log قديمة (> 30 يوم)
- *.tmp, *.bak
- .DS_Store, Thumbs.db
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("nova.agents.cleanup")


@dataclass
class CleanupResult:
    """نتيجة التنظيف"""
    ok: bool
    dry_run: bool
    files_deleted: int = 0
    dirs_deleted: int = 0
    bytes_freed: int = 0
    errors: List[str] = field(default_factory=list)
    elapsed: float = 0.0
    report: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "files_deleted": self.files_deleted,
            "dirs_deleted": self.dirs_deleted,
            "bytes_freed": self.bytes_freed,
            "mb_freed": round(self.bytes_freed / 1024 / 1024, 2),
            "errors": self.errors,
            "elapsed": self.elapsed,
        }


class CleanupAgent:
    """وكيل تنظيف الملفات المؤقتة"""

    # ═══════════════════════════════════════════════════════════
    # قوائم آمنة (Whitelist)
    # ═══════════════════════════════════════════════════════════

    # مجلدات يمكن حذفها بالكامل (cache directories)
    SAFE_CACHE_DIRS = {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "htmlcov",
        ".coverage",
        "*.egg-info",
    }

    # امتدادات ملفات مؤقتة
    SAFE_TEMP_EXTENSIONS = {
        ".pyc",
        ".pyo",
        ".pyd",
        ".tmp",
        ".bak",
        ".swp",
        ".swo",
    }

    # أسماء ملفات مؤقتة
    SAFE_TEMP_FILES = {
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        ".coverage",
        ".coverage.*",
    }

    # مجلدات يجب تجاهلها تماماً (لا نلمسها)
    PROTECTED_DIRS = {
        ".git", ".github",
        ".vault", ".secrets", ".ssh", ".cache", ".local",
        "venv", ".venv", "env", "site-packages", "node_modules",
        ".brain", ".hive", ".aider",
        "nova", "tools", "tests", "data", "docs",
        "hooks", "scripts", "deploy", "platform",
        "integration", "web", "reports", "config",
        "memory", "logs", "sandbox", "var", "workspace",
        "_organized", "_attic", "_archive", "_quarantine",
        "experiments", "generated", "releases", "projects",
    }

    def __init__(
        self,
        root: str = "/public",
        dry_run: bool = True,
        log_max_age_days: int = 30,
    ):
        """
        Args:
            root: المسار الجذر
            dry_run: True = معاينة فقط (آمن)، False = حذف فعلي
            log_max_age_days: احذف .log الأقدم من هذا
        """
        self.root = Path(root).resolve()
        self.dry_run = dry_run
        self.log_max_age_days = log_max_age_days
        self.stats = {
            "cache_dirs_found": 0,
            "temp_files_found": 0,
            "old_logs_found": 0,
            "errors": 0,
        }

    # ═══════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════

    def cleanup(
        self,
        target_dir: Optional[str] = None,
        include_logs: bool = True,
        include_cache: bool = True,
        include_temp: bool = True,
    ) -> CleanupResult:
        """
        تنظيف شامل.

        Args:
            target_dir: مجلد فرعي (None = الجذر)
            include_logs: حذف .log القديمة
            include_cache: حذف cache directories
            include_temp: حذف ملفات مؤقتة
        """
        start = time.time()
        scan_dir = self.root / target_dir if target_dir else self.root

        if not scan_dir.exists():
            return CleanupResult(
                ok=False,
                dry_run=self.dry_run,
                errors=[f"Not found: {scan_dir}"],
                elapsed=time.time() - start,
            )

        result = CleanupResult(ok=True, dry_run=self.dry_run)

        logger.info(f"🧹 Cleanup: {scan_dir} (dry_run={self.dry_run})")

        # ═══ 1. cache directories ═══
        if include_cache:
            self._cleanup_cache_dirs(scan_dir, result)

        # ═══ 2. temp files ═══
        if include_temp:
            self._cleanup_temp_files(scan_dir, result)

        # ═══ 3. old logs ═══
        if include_logs:
            self._cleanup_old_logs(scan_dir, result)

        result.elapsed = time.time() - start
        result.report = self._format_report(result)
        return result

    def preview(self, target_dir: Optional[str] = None) -> CleanupResult:
        """معاينة فقط (dry_run=True)"""
        old_state = self.dry_run
        self.dry_run = True
        try:
            return self.cleanup(target_dir=target_dir)
        finally:
            self.dry_run = old_state

    # ═══════════════════════════════════════════════════════════
    # Cache Dirs Cleanup
    # ═══════════════════════════════════════════════════════════

    def _cleanup_cache_dirs(self, scan_dir: Path, result: CleanupResult):
        """حذف cache directories"""
        for path in scan_dir.rglob("*"):
            if not path.is_dir():
                continue

            # تجاهل protected
            if any(part in self.PROTECTED_DIRS for part in path.parts):
                continue

            # تحقق من الاسم
            if path.name not in self.SAFE_CACHE_DIRS:
                continue

            # حساب الحجم
            size = self._dir_size(path)

            try:
                if not self.dry_run:
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info(f"🗑️  حذف cache: {path.relative_to(self.root)}")

                result.dirs_deleted += 1
                result.bytes_freed += size
                self.stats["cache_dirs_found"] += 1
            except Exception as e:
                result.errors.append(f"{path}: {str(e)[:80]}")
                self.stats["errors"] += 1

    # ═══════════════════════════════════════════════════════════
    # Temp Files Cleanup
    # ═══════════════════════════════════════════════════════════

    def _cleanup_temp_files(self, scan_dir: Path, result: CleanupResult):
        """حذف ملفات مؤقتة"""
        for path in scan_dir.rglob("*"):
            if not path.is_file():
                continue

            # تجاهل protected
            if any(part in self.PROTECTED_DIRS for part in path.parts):
                continue

            # تحقق
            should_delete = False

            # بالامتداد
            if path.suffix.lower() in self.SAFE_TEMP_EXTENSIONS:
                should_delete = True

            # بالاسم
            if path.name in self.SAFE_TEMP_FILES:
                should_delete = True

            if not should_delete:
                continue

            try:
                size = path.stat().st_size

                if not self.dry_run:
                    path.unlink()
                    logger.debug(f"🗑️  {path.relative_to(self.root)}")

                result.files_deleted += 1
                result.bytes_freed += size
                self.stats["temp_files_found"] += 1
            except Exception as e:
                result.errors.append(f"{path}: {str(e)[:80]}")
                self.stats["errors"] += 1

    # ═══════════════════════════════════════════════════════════
    # Old Logs Cleanup
    # ═══════════════════════════════════════════════════════════

    def _cleanup_old_logs(self, scan_dir: Path, result: CleanupResult):
        """حذف logs قديمة"""
        cutoff = time.time() - (self.log_max_age_days * 86400)

        for path in scan_dir.rglob("*.log"):
            if not path.is_file():
                continue

            # تجاهل protected
            if any(part in self.PROTECTED_DIRS for part in path.parts):
                continue

            # فحص العمر
            try:
                mtime = path.stat().st_mtime
                if mtime > cutoff:
                    continue  # حديث — لا تحذفه
            except OSError:
                continue

            try:
                size = path.stat().st_size

                if not self.dry_run:
                    path.unlink()
                    logger.debug(f"🗑️  log: {path.relative_to(self.root)}")

                result.files_deleted += 1
                result.bytes_freed += size
                self.stats["old_logs_found"] += 1
            except Exception as e:
                result.errors.append(f"{path}: {str(e)[:80]}")

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def _dir_size(self, path: Path) -> int:
        """حساب حجم مجلد"""
        total = 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _format_report(self, result: CleanupResult) -> str:
        """تنسيق التقرير"""
        mode = "🔍 معاينة (dry-run)" if self.dry_run else "🚀 تنفيذ فعلي"

        mb = result.bytes_freed / 1024 / 1024

        lines = [
            "╔" + "═" * 68 + "╗",
            f"║ 🧹 CleanupAgent — {mode:45s} ║",
            "╠" + "═" * 68 + "╣",
            f"║ 📁 Cache dirs:      {result.dirs_deleted:>6d}{34 * ' '} ║",
            f"║ 📄 Temp files:      {result.files_deleted:>6d}{34 * ' '} ║",
            f"║ 💾 Bytes freed:     {mb:>6.2f} MB{29 * ' '} ║",
            f"║ ⏱️  Elapsed:         {result.elapsed:>6.2f}s{33 * ' '} ║",
            f"║ ❌ Errors:           {len(result.errors):>6d}{34 * ' '} ║",
            "╚" + "═" * 68 + "╝",
        ]

        if self.dry_run:
            lines.append("\n💡 هذه معاينة فقط. للتنفيذ:")
            lines.append("   agent = CleanupAgent(dry_run=False)")
            lines.append("   agent.cleanup()")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Helper Function
# ═══════════════════════════════════════════════════════════════

def cleanup_temp_files(
    root: str = "/public",
    dry_run: bool = True,
    target_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """دالة مختصرة"""
    agent = CleanupAgent(root=root, dry_run=dry_run)
    result = agent.cleanup(target_dir=target_dir)
    return result.to_dict()


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

cleanup_agent = CleanupAgent(dry_run=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/public")
    parser.add_argument("--dir")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    agent = CleanupAgent(root=args.root, dry_run=not args.execute)
    result = agent.cleanup(target_dir=args.dir)
    print(result.report)
