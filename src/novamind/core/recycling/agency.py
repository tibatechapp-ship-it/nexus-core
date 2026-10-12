"""RecyclingAgency — وكالة معالجة النفايات البرمجية"""
from dataclasses import dataclass
from typing import Dict, List
from pathlib import Path
import time
import logging

from .waste_detector import WasteDetector
from .waste_fixer import WasteFixer
from .waste_recycler import WasteRecycler

logger = logging.getLogger("recycling.agency")


@dataclass
class CycleReport:
    cycle_id: int
    started_at: float
    ended_at: float = 0.0
    files_scanned: int = 0
    waste_found: int = 0
    waste_fixed: int = 0
    waste_recycled: int = 0
    duration: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "cycle_id": self.cycle_id,
            "files_scanned": self.files_scanned,
            "waste_found": self.waste_found,
            "waste_fixed": self.waste_fixed,
            "waste_recycled": self.waste_recycled,
            "duration": round(self.duration, 3),
        }


class RecyclingAgency:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.detector = WasteDetector()
        self.fixer = WasteFixer()
        self.recycler = WasteRecycler(base_dir)
        self.cycle_count = 0
        self.cycles: List[CycleReport] = []
        self.max_file_size = 1_000_000
        self.ignore = {"venv", "__pycache__", ".git", "node_modules"}

    def process_file(self, fp: Path, auto_fix: bool = False) -> Dict:
        if not fp.exists():
            return {"error": "not_found"}
        try:
            if fp.stat().st_size > self.max_file_size:
                return {"error": "too_large"}
        except Exception:
            return {"error": "stat_failed"}
        try:
            code = fp.read_text(encoding="utf-8")
        except Exception as e:
            return {"error": f"read_failed: {e}"}

        items = self.detector.scan_file(str(fp), code)
        result = {
            "file": str(fp),
            "waste_found": len(items),
            "fixed": 0,
            "recycled": 0,
        }

        if not items:
            return result

        if auto_fix:
            new_code = code
            for item in items:
                if item.fixable:
                    fix = self.fixer.fix(item, new_code)
                    if fix.success:
                        new_code = fix.fixed
                        result["fixed"] += 1
            if new_code != code:
                backup = fp.with_suffix(fp.suffix + ".bak")
                backup.write_text(code, encoding="utf-8")
                fp.write_text(new_code, encoding="utf-8")

        for item in items:
            if self.recycler.recycle(item, code):
                result["recycled"] += 1

        return result

    def process_directory(self, directory: Path, auto_fix: bool = False) -> CycleReport:
        self.cycle_count += 1
        report = CycleReport(self.cycle_count, time.time())

        for py in Path(directory).rglob("*.py"):
            if any(ig in str(py) for ig in self.ignore):
                continue
            report.files_scanned += 1
            r = self.process_file(py, auto_fix)
            if "error" in r:
                continue
            report.waste_found += r["waste_found"]
            report.waste_fixed += r["fixed"]
            report.waste_recycled += r["recycled"]

        report.ended_at = time.time()
        report.duration = report.ended_at - report.started_at
        self.cycles.append(report)
        return report

    def stats(self) -> Dict:
        return {
            "cycles": self.cycle_count,
            "files_scanned": sum(c.files_scanned for c in self.cycles),
            "waste_found": sum(c.waste_found for c in self.cycles),
            "waste_fixed": sum(c.waste_fixed for c in self.cycles),
            "waste_recycled": sum(c.waste_recycled for c in self.cycles),
            "detector": self.detector.stats(),
            "fixer": self.fixer.stats(),
            "recycler": self.recycler.stats(),
        }
