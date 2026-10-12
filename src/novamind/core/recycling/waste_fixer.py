"""WasteFixer — مصلح النفايات"""
from dataclasses import dataclass
from typing import Dict, List
import ast
import re
import logging

from .waste_detector import WasteItem, WasteType

logger = logging.getLogger("recycling.fixer")


@dataclass
class FixResult:
    waste_id: str
    success: bool
    original: str
    fixed: str
    strategy: str
    error: str = ""


class WasteFixer:
    def __init__(self):
        self.applied = 0
        self.failed = 0
        self.history: List[FixResult] = []

    def fix(self, item: WasteItem, code: str) -> FixResult:
        try:
            if item.waste_type == WasteType.UNUSED_IMPORT:
                fixed = self._unused(item, code)
            elif item.waste_type == WasteType.DEPRECATED:
                fixed = self._deprecated(item, code)
            elif item.waste_type == WasteType.UNSAFE:
                fixed = self._unsafe(item, code)
            elif item.waste_type == WasteType.BROKEN:
                fixed = self._broken(item, code)
            else:
                return FixResult(item.waste_id, False, code, code,
                                 "unsupported", "لا استراتيجية")
            try:
                ast.parse(fixed)
            except SyntaxError as e:
                self.failed += 1
                return FixResult(item.waste_id, False, code, code,
                                 "verify_failed", f"معطوب: {e}")
            self.applied += 1
            r = FixResult(item.waste_id, True, code, fixed, item.waste_type.value)
            self.history.append(r)
            return r
        except Exception as e:
            self.failed += 1
            return FixResult(item.waste_id, False, code, code, "error", str(e))

    def _unused(self, item, code):
        lines = code.split("\n")
        idx = item.line_start - 1
        if 0 <= idx < len(lines):
            lines.pop(idx)
        return "\n".join(lines)

    def _deprecated(self, item, code):
        r = {
            "datetime.utcnow()": "datetime.now(timezone.utc)",
        }
        fixed = code
        for old, new in r.items():
            fixed = fixed.replace(old, new)
        return fixed

    def _unsafe(self, item, code):
        r = [
            (r"os\.system\s*\(([^)]+)\)", r"subprocess.run(\1, shell=False)"),
            (r"yaml\.load\s*\(([^,)]+)\)", r"yaml.safe_load(\1)"),
        ]
        fixed = code
        for p, rep in r:
            fixed = re.sub(p, rep, fixed)
        return fixed

    def _broken(self, item, code):
        fixed = code
        fixed = re.sub(r"(def\s+\w+\s*\([^)]*\))\s*\n", r"\1:\n", fixed)
        fixed = re.sub(r"(if|for|while|def|class)\s+([^\n:]+)\n", r"\1 \2:\n", fixed)
        return fixed

    def stats(self) -> Dict:
        return {
            "fixes_applied": self.applied,
            "fixes_failed": self.failed,
            "success_rate": round(self.applied / max(1, self.applied + self.failed), 3),
        }
