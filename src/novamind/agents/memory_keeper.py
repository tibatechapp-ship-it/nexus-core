"""
MemoryKeeperAgent — وكيل حفظ الدروس
=======================================
يحفظ كل خطأ وحله في قاعدة معرفة مشتركة.

الملف: .nova_memory.jsonl
كل سطر: {"error": "...", "fix": "...", "commit": "...", "date": "..."}
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nova.agents.memory_keeper")

MEMORY_FILE = os.getenv(
    "NOVA_MEMORY",
    "/public/.nova_memory.jsonl"
)


@dataclass
class Lesson:
    """درس مستفاد"""
    error_type: str
    error_msg: str
    root_cause: str
    fix: str
    commit: str
    date: str
    agent: str = "system"


class MemoryKeeperAgent:
    """وكيل حفظ الدروس"""

    def __init__(self, memory_file: str = MEMORY_FILE):
        self.memory_file = Path(memory_file)
        self.lessons: List[Lesson] = []
        self._load()

    def _load(self) -> None:
        """يحمل الدروس المحفوظة."""
        if not self.memory_file.exists():
            return
        
        try:
            with open(self.memory_file) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self.lessons.append(Lesson(**data))
        except Exception as e:
            logger.warning(f"Could not load memory: {e}")

    def remember(
        self,
        error_type: str,
        error_msg: str,
        root_cause: str,
        fix: str,
        commit: str = "",
        agent: str = "system",
    ) -> None:
        """يحفظ درساً جديداً."""
        lesson = Lesson(
            error_type=error_type,
            error_msg=error_msg,
            root_cause=root_cause,
            fix=fix,
            commit=commit,
            date=datetime.now().isoformat(timespec="seconds"),
            agent=agent,
        )
        
        self.lessons.append(lesson)
        
        # Append to file
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.memory_file, "a") as f:
            f.write(json.dumps(asdict(lesson), ensure_ascii=False) + "\n")
        
        logger.info(f"📝 Lesson saved: {error_type}")

    def recall(self, error_type: str) -> List[Lesson]:
        """يسترجع الدروس المتعلقة."""
        return [l for l in self.lessons if error_type in l.error_type]

    def report(self) -> str:
        """يولّد تقريراً."""
        lines = [f"📚 Memory: {len(self.lessons)} درس", ""]
        
        # Group by error_type
        by_type: Dict[str, int] = {}
        for l in self.lessons:
            by_type[l.error_type] = by_type.get(l.error_type, 0) + 1
        
        for err_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {err_type}: {count} مرة")
        
        return "\n".join(lines)


def remember(
    error_type: str, error_msg: str,
    root_cause: str, fix: str,
    commit: str = "",
) -> None:
    """Wrapper."""
    MemoryKeeperAgent().remember(
        error_type, error_msg, root_cause, fix, commit
    )
