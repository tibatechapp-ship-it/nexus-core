"""WasteDetector — كاشف النفايات البرمجية"""
from dataclasses import dataclass
from typing import Dict, List, Tuple
from enum import Enum
import ast
import re
import hashlib
import time
import logging

logger = logging.getLogger("recycling.detector")


class WasteType(Enum):
    BROKEN = "broken"
    DUPLICATED = "duplicated"
    DEAD = "dead"
    DEPRECATED = "deprecated"
    UNSAFE = "unsafe"
    UNUSED_IMPORT = "unused_import"


class Severity(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class WasteItem:
    waste_id: str
    waste_type: WasteType
    severity: Severity
    file_path: str
    line_start: int
    line_end: int
    snippet: str
    description: str
    fixable: bool = True
    detected_at: float = 0.0

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = time.time()

    def to_dict(self) -> Dict:
        return {
            "waste_id": self.waste_id,
            "type": self.waste_type.value,
            "severity": self.severity.name,
            "file": self.file_path,
            "lines": f"{self.line_start}-{self.line_end}",
            "snippet": self.snippet[:120],
            "description": self.description,
        }


class WasteDetector:
    DEPRECATED = [
        (r"import\s+imp\b", "وحدة imp مهملة"),
        (r"from\s+distutils", "distutils مهمل"),
        (r"datetime\.utcnow\s*\(", "utcnow() مهمل"),
    ]
    UNSAFE = [
        (r"\beval\s*\(", "eval خطير"),
        (r"\bexec\s*\(", "exec خطير"),
        (r"os\.system\s*\(", "shell مباشر"),
        (r"pickle\.loads\s*\(", "pickle خطير"),
    ]

    def __init__(self):
        self.counter = 0
        self.detected: List[WasteItem] = []

    def _id(self) -> str:
        self.counter += 1
        return f"W-{int(time.time())}-{self.counter:04d}"

    def detect_broken(self, fp: str, code: str) -> List[WasteItem]:
        try:
            ast.parse(code)
            return []
        except SyntaxError as e:
            return [WasteItem(
                self._id(), WasteType.BROKEN, Severity.CRITICAL,
                fp, e.lineno or 0, e.lineno or 0,
                e.text or "", f"SyntaxError: {e.msg}",
            )]

    def detect_duplicated(self, files: Dict[str, str]) -> List[WasteItem]:
        items = []
        seen: Dict[str, List[Tuple[str, int, str]]] = {}
        for fp, code in files.items():
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    try:
                        src = ast.unparse(node)
                    except Exception:
                        continue
                    h = hashlib.md5(src.encode(), usedforsecurity=False).hexdigest()
                    seen.setdefault(h, []).append((fp, node.lineno, node.name))
        for h, places in seen.items():
            if len(places) > 1:
                locs = ", ".join(f"{p[0]}:{p[1]}" for p in places)
                items.append(WasteItem(
                    self._id(), WasteType.DUPLICATED, Severity.MEDIUM,
                    places[0][0], places[0][1], places[0][1],
                    places[0][2], f"مكرر في: {locs}",
                ))
        return items

    def detect_dead(self, fp: str, code: str) -> List[WasteItem]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        items = []
        defs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[node.name] = node
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used.add(node.value.id)
        for name, node in defs.items():
            if name.startswith("_"):
                continue
            if name not in used:
                items.append(WasteItem(
                    self._id(), WasteType.DEAD, Severity.LOW,
                    fp, node.lineno,
                    getattr(node, "end_lineno", node.lineno),
                    name, f"غير مستخدم: {name}",
                ))
        return items

    def detect_deprecated(self, fp: str, code: str) -> List[WasteItem]:
        items = []
        for pattern, desc in self.DEPRECATED:
            for m in re.finditer(pattern, code):
                line = code[:m.start()].count("\n") + 1
                items.append(WasteItem(
                    self._id(), WasteType.DEPRECATED, Severity.MEDIUM,
                    fp, line, line, m.group(0)[:80], desc,
                ))
        return items

    def detect_unsafe(self, fp: str, code: str) -> List[WasteItem]:
        items = []
        for pattern, desc in self.UNSAFE:
            for m in re.finditer(pattern, code):
                line = code[:m.start()].count("\n") + 1
                items.append(WasteItem(
                    self._id(), WasteType.UNSAFE, Severity.HIGH,
                    fp, line, line, m.group(0)[:80], desc,
                ))
        return items

    def detect_unused_imports(self, fp: str, code: str) -> List[WasteItem]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    name = (a.asname or a.name).split(".")[0]
                    imports[name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "*":
                        continue
                    imports[a.asname or a.name] = node.lineno
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used.add(node.value.id)
        items = []
        for name, line in imports.items():
            if name not in used:
                items.append(WasteItem(
                    self._id(), WasteType.UNUSED_IMPORT, Severity.LOW,
                    fp, line, line, f"import {name}",
                    f"استيراد غير مستخدم: {name}",
                ))
        return items

    def scan_file(self, fp: str, code: str) -> List[WasteItem]:
        items = []
        items.extend(self.detect_broken(fp, code))
        items.extend(self.detect_dead(fp, code))
        items.extend(self.detect_deprecated(fp, code))
        items.extend(self.detect_unsafe(fp, code))
        items.extend(self.detect_unused_imports(fp, code))
        self.detected.extend(items)
        return items

    def stats(self) -> Dict:
        by_type: Dict[str, int] = {}
        by_sev: Dict[str, int] = {}
        for it in self.detected:
            by_type[it.waste_type.value] = by_type.get(it.waste_type.value, 0) + 1
            by_sev[it.severity.name] = by_sev.get(it.severity.name, 0) + 1
        return {
            "total_detected": len(self.detected),
            "by_type": by_type,
            "by_severity": by_sev,
        }
