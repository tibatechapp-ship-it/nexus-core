"""
Multi-File Editor - Edit multiple files atomically
"""
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("multi_file_editor")


class MultiFileEditor:
    def __init__(self):
        self.changes: List[Dict] = []

    def stage(self, path: str, old: str, new: str):
        """Stages a file edit."""
        p = Path(path)
        if not p.exists():
            return {"ok": False, "error": "file not found"}

        content = p.read_text(encoding="utf-8")
        if old not in content:
            return {"ok": False, "error": "old string not found"}

        self.changes.append({
            "path": path,
            "old": old,
            "new": new,
            "original": content,
        })
        return {"ok": True, "staged": len(self.changes)}

    def commit(self) -> Dict:
        """Applies all staged changes."""
        applied = 0
        errors = []

        for change in self.changes:
            try:
                path = Path(change["path"])
                content = change["original"].replace(
                    change["old"], change["new"], 1
                )
                path.write_text(content, encoding="utf-8")
                applied += 1
            except Exception as e:
                errors.append(str(e)[:100])

        result = {
            "ok": applied == len(self.changes),
            "applied": applied,
            "total": len(self.changes),
            "errors": errors,
        }
        self.changes = []
        return result


multi_editor = MultiFileEditor()
