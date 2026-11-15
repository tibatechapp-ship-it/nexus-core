"""قسم ذكاء المستودع — خريطة معمارية، رسم استيراد، وتحليل تأثير.

القواعد المعلنة:

* **تحليل ساكن خالص**: ``ast`` قياسي — لا استيراد حقيقي لأي وحدة
  مستودع ولا تنفيذ لأي كود. قراءة نصوص وتحليل بنية فقط.
* **معرفات حتمية**: ملف نفسه يعطي نفس بصمة SHA-256 — الفهرسة التزايدية
  تتخطى ما لم يتغير، وأي تغيير يعيد تحليل الملف فقط.
* **رسم معرفي صريح**: عقد (وحدات، دوال، أصناف) وحواف (استيراد، احتواء)
  بقواميس حتمية الترتيب — نفس المستودع يعطي نفس الرسم حرفيًا.
* **تحليل التأثير بالعكس**: ملفات متأثرة من تغيير = مستوردو الملف
  المُغيَّر عكسًا حتى عمق معلن — أساس تخطيط التنفيذ والاختبار.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["RepoMap", "RepoIntelligence", "file_fingerprint"]

#: الامتدادات المُحلَّلة — Python أولًا؛ لغات أخرى تُكتشف ولا تُحلَّل AST.
PYTHON_SUFFIX = ".py"

#: تخطي المجلدات غير المصدرية.
SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules",
                       "data", "dist", "build", ".mypy_cache"})


def file_fingerprint(path: Path) -> str:
    """بصمة ملف حتمية — SHA-256 للمحتوى، أساس الفهرسة التزايدية."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@dataclass
class ModuleInfo:
    """معلومة وحدة واحدة — ملف ودواله وأصنافه واستيراداته."""

    rel_path: str
    language: str = "python"
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    lines: int = 0
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path, "language": self.language,
            "functions": self.functions, "classes": self.classes,
            "imports": self.imports, "lines": self.lines,
            "fingerprint": self.fingerprint,
        }


@dataclass
class RepoMap:
    """خريطة مستودع كاملة — وحدات، رسم استيراد، رسم معرفي، لغات."""

    root: str
    modules: list[ModuleInfo] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    files_scanned: int = 0
    files_skipped_unchanged: int = 0

    def module_names(self) -> list[str]:
        """أسماء الوحدات كبايثون (بدون .py وبفواصل نقطية) — حتمي."""
        return [m.rel_path[:-3].replace("/", ".")
                for m in self.modules if m.rel_path.endswith(PYTHON_SUFFIX)]

    def import_edges(self) -> list[tuple[str, str]]:
        """حواف الاستيراد الداخلي — من وحدة إلى وحدة داخل نفس المستودع."""
        names = set(self.module_names())
        edges: list[tuple[str, str]] = []
        for m in self.modules:
            if not m.rel_path.endswith(PYTHON_SUFFIX):
                continue
            src = m.rel_path[:-3].replace("/", ".")
            for imp in m.imports:
                if imp in names:
                    edges.append((src, imp))
        return sorted(set(edges))

    def reverse_imports(self, module: str) -> list[str]:
        """مستوردو وحدة مباشرة — حتمي مرتب."""
        target = module.removesuffix(".py").replace("/", ".")
        return sorted({src for src, dst in self.import_edges() if dst == target})

    def knowledge_graph(self) -> dict[str, Any]:
        """رسم معرفي حتمي — عقد وحواف بترتيب ثابت قابل للاختبار."""
        nodes: list[dict[str, str]] = []
        edges: list[dict[str, str]] = []
        for m in sorted(self.modules, key=lambda x: x.rel_path):
            base = m.rel_path
            nodes.append({"id": f"module:{base}", "kind": "module"})
            for fn in m.functions:
                nodes.append({"id": f"func:{base}:{fn}", "kind": "function"})
                edges.append({"src": f"module:{base}",
                              "dst": f"func:{base}:{fn}", "rel": "contains"})
            for cls in m.classes:
                nodes.append({"id": f"class:{base}:{cls}", "kind": "class"})
                edges.append({"src": f"module:{base}",
                              "dst": f"class:{base}:{cls}", "rel": "contains"})
        for src, dst in self.import_edges():
            edges.append({"src": f"module:{src}.py",
                          "dst": f"module:{dst}.py", "rel": "imports"})
        return {"nodes": nodes, "edges": edges}

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "modules": [m.to_dict() for m in self.modules],
            "languages": dict(sorted(self.languages.items())),
            "files_scanned": self.files_scanned,
            "files_skipped_unchanged": self.files_skipped_unchanged,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)


class RepoIntelligence:
    """محرك ذكاء المستودع — فهرسة تزايدية + تأثير + رسم معرفي."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._modules_cache: dict[str, ModuleInfo] = {}

    def scan(self, incremental: bool = True) -> RepoMap:
        """مسح كامل أو تزايدي — المتغير يُعاد تحليله والتثابت يُتخطى."""
        repo_map = RepoMap(root=str(self.root))
        py_files: list[Path] = []
        other_files: dict[str, int] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix == PYTHON_SUFFIX:
                py_files.append(path)
                repo_map.languages["python"] = \
                    repo_map.languages.get("python", 0) + 1
            else:
                other_files[path.suffix or "<none>"] = \
                    other_files.get(path.suffix or "<none>", 0) + 1
        repo_map.languages.update(
            {k: v for k, v in sorted(other_files.items())})
        fresh_cache: dict[str, ModuleInfo] = {}
        for path in py_files:
            rel = str(path.relative_to(self.root))
            fp = file_fingerprint(path)
            cached = self._modules_cache.get(rel)
            if incremental and cached is not None and cached.fingerprint == fp:
                # التزايدي الصحيح: الملف لم يتغير → معلومة المحلل السابق
                # تُستخدم كما هي (skip تحليل) والوحدة تبقى كاملة في الخريطة
                repo_map.modules.append(cached)
                repo_map.files_skipped_unchanged += 1
                fresh_cache[rel] = cached
                continue
            info = self._parse_module(path, rel, fp)
            repo_map.modules.append(info)
            fresh_cache[rel] = info
        self._modules_cache = fresh_cache   # الملفات المحذوفة تخرج من الكاش
        repo_map.files_scanned = len(py_files)
        return repo_map

    def _parse_module(self, path: Path, rel: str, fp: str) -> ModuleInfo:
        """تحليل AST لملف واحد — قراءة نص لا تنفيذ."""
        info = ModuleInfo(rel_path=rel, fingerprint=fp)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            info.language = "python-broken"
            info.lines = len(
                path.read_text(encoding="utf-8", errors="ignore").splitlines())
            return info
        info.lines = sum(1 for _ in open(path, encoding="utf-8",
                                         errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                info.functions.append(node.name)
            elif isinstance(node, ast.AsyncFunctionDef):
                info.functions.append(f"async {node.name}")
            elif isinstance(node, ast.ClassDef):
                info.classes.append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    info.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    info.imports.append(node.module)
        return info

    # ── تحليل التأثير ─────────────────────────────────────────────────────

    def affected_files(self, changed: list[str],
                       depth: int = 2) -> dict[str, Any]:
        """تأثير تغيير معلن — الملف نفسه + مستوردوه عكسًا حتى عمق معلن.

        العودة قاموس حتمي: ``direct`` (المُغيَّر نفسه)، ``transitive``
        (المستوردون بالعكس)، ``depth`` المعلن، و``test_files`` ملفات
        الاختبار المرشحة للإعادة.
        """
        repo_map = self.scan()
        modules_by_rel = {m.rel_path: m for m in repo_map.modules}
        transitive: set[str] = set()
        frontier = [c for c in changed if c in modules_by_rel]
        for _ in range(max(0, depth)):
            nxt: list[str] = []
            for rel in frontier:
                mod_name = rel[:-3].replace("/", ".")
                for importer in repo_map.reverse_imports(mod_name):
                    # عكس الاستيراد يعيد اسم وحدة نقطيًا — يُحوَّل لمسار ملف
                    importer_rel = importer.replace(".", "/") + ".py"
                    if importer_rel not in transitive                             and importer_rel not in changed:
                        transitive.add(importer_rel)
                        nxt.append(importer_rel)
            frontier = nxt
        test_files = sorted(
            rel for rel in list(changed) + sorted(transitive)
            if "test" in Path(rel).name)
        return {
            "changed": sorted(changed),
            "direct": sorted(set(changed) & set(modules_by_rel)),
            "transitive": sorted(transitive),
            "depth": depth,
            "test_files": test_files,
        }

    def summary_for_planning(self, repo_map: RepoMap | None = None) -> dict[str, Any]:
        """ملخص تخطيطي حتمي — مُدخل قسم الذكاء إلى المُنسّق."""
        rm = repo_map or self.scan()
        entry_points = [
            m.rel_path for m in sorted(rm.modules, key=lambda x: x.rel_path)
            if Path(m.rel_path).name in ("main.py", "__main__.py", "cli.py",
                                         "app.py", "server.py")
        ]
        return {
            "root": str(self.root),
            "python_modules": len(rm.modules),
            "languages": dict(sorted(rm.languages.items())),
            "import_edges": len(rm.import_edges()),
            "entry_points": entry_points,
            "knowledge_graph_nodes": len(rm.knowledge_graph()["nodes"]),
        }
