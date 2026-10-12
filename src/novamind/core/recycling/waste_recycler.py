"""WasteRecycler — معيد تدوير النفايات"""
from dataclasses import dataclass
from typing import Dict, List, Optional
from pathlib import Path
import time
import json
import logging

from .waste_detector import WasteItem, WasteType

logger = logging.getLogger("recycling.recycler")


@dataclass
class RecycledItem:
    original_id: str
    recycle_type: str
    content: str
    reusable: bool
    stored_at: str
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()


class WasteRecycler:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir) / ".nova" / "recycled"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir = self.base_dir / "library"
        self.library_dir.mkdir(exist_ok=True)
        self.snippets_dir = self.base_dir / "snippets"
        self.snippets_dir.mkdir(exist_ok=True)
        self.recycled: List[RecycledItem] = []

    def recycle(self, item: WasteItem, code: str) -> Optional[RecycledItem]:
        if item.waste_type == WasteType.DEAD:
            return self._dead(item)
        elif item.waste_type == WasteType.DUPLICATED:
            return self._dup(item)
        elif item.waste_type == WasteType.DEPRECATED:
            return self._dep(item)
        return None

    def _dead(self, item):
        f = self.library_dir / f"dead_{item.waste_id}.py"
        f.write_text(
            f"# Recycled from: {item.file_path}\n"
            f"# {item.description}\n"
            f"# {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"{item.snippet}\n",
            encoding="utf-8",
        )
        r = RecycledItem(item.waste_id, "library", item.snippet, True, str(f))
        self.recycled.append(r)
        return r

    def _dup(self, item):
        f = self.snippets_dir / f"dup_{item.waste_id}.py"
        f.write_text(
            f"# Duplicated pattern — {item.description}\n"
            f"# From: {item.file_path}\n\n"
            f"{item.snippet}\n",
            encoding="utf-8",
        )
        r = RecycledItem(item.waste_id, "shared_snippet", item.snippet, True, str(f))
        self.recycled.append(r)
        return r

    def _dep(self, item):
        f = self.library_dir / f"dep_{item.waste_id}.json"
        data = {"deprecated": item.snippet, "file": item.file_path, "line": item.line_start}
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        r = RecycledItem(item.waste_id, "deprecation_note",
                         json.dumps(data, ensure_ascii=False), False, str(f))
        self.recycled.append(r)
        return r

    def stats(self) -> Dict:
        by_type: Dict[str, int] = {}
        for r in self.recycled:
            by_type[r.recycle_type] = by_type.get(r.recycle_type, 0) + 1
        return {"total_recycled": len(self.recycled), "by_type": by_type}
