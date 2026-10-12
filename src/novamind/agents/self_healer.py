"""
SelfHealerAgent — وكيل المعالجة الذاتية
==========================================
يصلح الأخطاء المعروفة تلقائياً بدون تدخل بشري.

القواعد:
✅ dry_run=True افتراضي
✅ فقط الأخطاء المعروفة
✅ يحفظ نسخة احتياطية قبل التعديل
✅ يسجل كل تعديل
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nova.agents.self_healer")


# إصلاحات معروفة (Pattern → Replacement)
KNOWN_FIXES: List[Dict[str, str]] = [
    {
        "name": "NOVAMIND_HOME fallback",
        "pattern": r'ROOT\s*=\s*Path\(os\.getenv\("HIVE_ROOT",\s*"/public"\)\)',
        "replacement": (
            '_candidate = (\n'
            '    os.getenv("NOVAMIND_HOME")\n'
            '    or os.getenv("HIVE_ROOT")\n'
            '    or str(Path(__file__).resolve().parents[2])\n'
            ')\n'
            'ROOT = Path(_candidate)'
        ),
        "files": ["nova/analytics/*.py"],
    },
    {
        "name": "Missing import can_agent_use_tool",
        "pattern": r"from hive\.factory\.guards import build_default_chain$",
        "replacement": "from hive.factory.guards import build_default_chain, can_agent_use_tool",
        "files": ["hive/factory/executor.py"],
    },
]


@dataclass
class FixResult:
    """نتيجة إصلاح"""
    ok: bool
    dry_run: bool
    file: str
    fix_name: str
    changes: int = 0
    backup: Optional[str] = None


class SelfHealerAgent:
    """وكيل المعالجة الذاتية"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.results: List[FixResult] = []

    def heal(self, target_dir: Path) -> List[FixResult]:
        """يصلح كل الأخطاء المعروفة في المجلد."""
        for fix in KNOWN_FIXES:
            for pattern_glob in fix["files"]:
                for file_path in target_dir.glob(pattern_glob):
                    self._apply_fix(file_path, fix)
        return self.results

    def _apply_fix(self, file_path: Path, fix: Dict[str, str]) -> None:
        """يطبق إصلاحاً واحداً."""
        try:
            content = file_path.read_text(encoding='utf-8')
            new_content, count = re.subn(
                fix["pattern"], fix["replacement"], content
            )
            
            if count == 0:
                return
            
            if self.dry_run:
                self.results.append(FixResult(
                    ok=True, dry_run=True,
                    file=str(file_path), fix_name=fix["name"],
                    changes=count,
                ))
                return
            
            # Backup
            backup = file_path.with_suffix(
                file_path.suffix + f".bak.{datetime.now():%Y%m%d_%H%M%S}"
            )
            shutil.copy2(file_path, backup)
            
            # Apply
            file_path.write_text(new_content, encoding='utf-8')
            
            self.results.append(FixResult(
                ok=True, dry_run=False,
                file=str(file_path), fix_name=fix["name"],
                changes=count, backup=str(backup),
            ))
            
            logger.info(f"✅ Fixed {file_path}: {fix['name']} ({count} changes)")
            
        except Exception as e:
            logger.error(f"❌ Failed {file_path}: {e}")
            self.results.append(FixResult(
                ok=False, dry_run=self.dry_run,
                file=str(file_path), fix_name=fix["name"],
            ))


def auto_heal(target_dir: str = "/public", dry_run: bool = True) -> str:
    """Wrapper."""
    agent = SelfHealerAgent(dry_run=dry_run)
    results = agent.heal(Path(target_dir))
    
    lines = [
        f"🔧 Self-Healer ({'DRY-RUN' if dry_run else 'LIVE'})",
        f"الإصلاحات: {len(results)}",
        "",
    ]
    for r in results:
        mark = "✅" if r.ok else "❌"
        lines.append(f"{mark} {r.file}: {r.fix_name} ({r.changes} changes)")
    return "\n".join(lines)
