"""File Guard — يتحقق من وجود وصحة الملفات."""
from __future__ import annotations
from typing import Dict, Any, List
from pathlib import Path

from novamind.factory.guards.base import GuardResult


class FileGuard:
    name = "file_guard"

    def __init__(self, required_files: List[str] = None, base_dir: str | None = None):
        self.required_files = required_files or []
        self.base_dir = Path(base_dir) if base_dir else None

    def check(self, data: Dict[str, Any]) -> GuardResult:
        result = GuardResult(passed=True, guard_name=self.name)

        # فحص ملفات في data["files"]
        files = data.get("files")
        if files is not None:
            if not isinstance(files, list):
                result.add_error("files must be a list")
            else:
                for f in files:
                    if isinstance(f, str):
                        if not f.strip():
                            result.add_error("empty file path")
                    elif isinstance(f, dict):
                        if "path" not in f:
                            result.add_error("file missing path")

        # فحص الملفات المطلوبة على القرص
        if self.base_dir:
            for rel in self.required_files:
                full = self.base_dir / rel
                if not full.exists():
                    result.add_error(f"missing file: {rel}")
                elif full.is_file() and full.stat().st_size == 0:
                    if not rel.endswith("__init__.py"):
                        result.add_warning(f"empty file: {rel}")

        return result
