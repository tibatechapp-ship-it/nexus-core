"""
SemanticMemory - Persistent lesson storage
- Stores lessons in .nova/agents.md
- Keeps last 250 lines (newest)
- Deletes oldest when limit exceeded
- Supports keyword search
"""
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime, timezone
import sys

# Import vfs
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))
from novamind.core.vfs import vfs, VfsError


AGENTS_FILE = ".nova/agents.md"
MAX_LINES = 250
MAX_LINE_LENGTH = 300


class SemanticMemory:
    def __init__(self):
        self._cache: Optional[str] = None

    def _ensure_file(self) -> None:
        """Creates the file if it does not exist"""
        if not vfs.exists(AGENTS_FILE):
            vfs.write(AGENTS_FILE, "# AGENTS.md - Project Memory\n\n")

    def load(self, limit: int = 30) -> str:
        """Reads last N lines (newest first)"""
        if not vfs.exists(AGENTS_FILE):
            return ""

        try:
            content = vfs.read(AGENTS_FILE)
            lines = [l for l in content.split("\n") if l.strip()]

            if not lines:
                return ""

            header = ""
            for l in lines:
                if l.startswith("#"):
                    header = l
                    break

            body = [l for l in lines if not l.startswith("#")][-limit:]

            result = [header] + body if header else body
            self._cache = "\n".join(result)
            return self._cache
        except VfsError as e:
            print("[semantic] read error: " + str(e))
            return ""

    def append(self, text: str, source: str = "", confidence: Optional[float] = None) -> None:
        """Adds a lesson - deletes oldest when exceeding MAX_LINES"""
        text = (text or "").strip()[:MAX_LINE_LENGTH]
        if not text:
            return

        self._ensure_file()
        content = vfs.read(AGENTS_FILE)
        lines = [l for l in content.split("\n") if l.strip()]

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        entry = "- [" + timestamp + "] " + text
        if confidence is not None:
            entry += " (conf: " + format(confidence, ".2f") + ")"
        if source:
            entry += " -- " + source

        if len(lines) >= MAX_LINES:
            headers = [l for l in lines if l.startswith("#")]
            bodies = [l for l in lines if not l.startswith("#")]
            bodies = bodies[-(MAX_LINES - 1):]
            content = "\n".join(headers + bodies) + "\n"

        vfs.write(AGENTS_FILE, content + entry + "\n")
        self._cache = None
        print("[semantic] saved lesson: " + text[:60])

    def search(self, keyword: str, limit: int = 5) -> List[str]:
        """Searches lessons by keyword"""
        if not vfs.exists(AGENTS_FILE):
            return []
        content = vfs.read(AGENTS_FILE)
        kw = keyword.lower()
        results = []
        for line in content.split("\n"):
            if line.startswith("- [") and kw in line.lower():
                results.append(line)
                if len(results) >= limit:
                    break
        return results

    def count(self) -> int:
        """Number of stored lessons"""
        if not vfs.exists(AGENTS_FILE):
            return 0
        content = vfs.read(AGENTS_FILE)
        return sum(1 for l in content.split("\n") if l.startswith("- ["))

    def clear(self) -> None:
        """Removes all lessons"""
        vfs.write(AGENTS_FILE, "# AGENTS.md - Project Memory\n\n")
        self._cache = None

    def raw(self) -> str:
        """Returns raw file content"""
        if not vfs.exists(AGENTS_FILE):
            return ""
        return vfs.read(AGENTS_FILE)


# Singleton
semantic_memory = SemanticMemory()
