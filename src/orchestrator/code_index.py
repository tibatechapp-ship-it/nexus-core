"""فهرس الذكاء — خريطة رموز المستودع تُبنى مرة وتُسأل ألف مرة.

الفكرة الواحدة: الوكيل لا يقرأ المستودع ليوجد «أين يُعرَّف X ومَن يستورده»؛
الفهرس يُبنى بـ ``ast`` وحده (لا تنفيذ، لا شبكة، لا تقييم كود)، ويُخزّن JSON،
وكل استعلام يعيد **شريحة سياق مضغوطة** تُدخل في برومبت الوكيل كما هي —
فتقل التوكِنات وترتفع دقة التوجيه.

العقد:
* ``build_index(root)`` → قاموس الفهرس (ملفات، رموز، مستوردات، أزمنة).
* ``CodeIndex.load/save`` → دورة كاملة على القرص مع كشف البُهتان.
* ``lookup(name)`` → التعريفات · ``refs(name)`` → المستوردون والمُعرِّفون ·
  ``slice(name)`` → النص المضغوط الجاهز للبرومبت.
* ``is_stale(root)`` → ملف تغيّر أو حُذف أو وُجد جديد ⇒ الفهرس باهت.
"""

from __future__ import annotations

import ast
import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

__all__ = ["INDEX_VERSION", "IGNORED_DIRS", "build_index", "CodeIndex", "slice_for"]

#: نسخة مخطط الفهرس — يتغير الرقم مع أي تغيير حقلي لا يُفهم رجوعاً.
INDEX_VERSION = 1

#: مجلدات لا تُمسح أبداً (بنية لا كود تشغيلي).
IGNORED_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
    ".tox", ".eggs",
})


def iter_python_files(root: Path) -> Iterator[Path]:
    """كل ملف ``*.py`` تحت الجذر — بترتيب ثابت (مرتّب) وبلا مجلدات مهملة."""
    for path in sorted(root.rglob("*.py")):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """توقيع مختصر — الاسم والمعاملات فقط، بلا جسم."""
    try:
        args = [a.arg for a in node.args.args]
        if node.args.vararg:
            args.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            args.append("**" + node.args.kwarg.arg)
        name = getattr(node, "name", "<anon>")
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {name}({', '.join(args)})"
    except Exception:  # noqa: BLE001 — التوقيع اختياري لا يهدم الفهرس
        return getattr(node, "name", "<anon>")


def build_index(root: Path) -> dict[str, Any]:
    """ابنِ الفهرس من الشجرة — حتمي: نفس الشجرة تعطي نفس الفهرس.

    التالف يُتجاوز بصمت معلن (حقل ``errors``) — ملف باهت لا يمنع فهرسة
    الباقي؛ هذا مبدأ الفهرس لا مبدأ المترجم.
    """
    root = Path(root).resolve()
    files: dict[str, Any] = {}
    errors: list[str] = []
    for path in iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError) as exc:
            errors.append(f"{rel}: {type(exc).__name__}")
            continue
        classes: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        imports: list[str] = []
        bound_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "line": node.lineno,
                    "methods": [n.name for n in node.body
                                if isinstance(n, (ast.FunctionDef,
                                                  ast.AsyncFunctionDef))],
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "signature": _signature(node),
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    bound_names.append(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
                for alias in node.names:
                    if alias.name != "*":
                        bound_names.append(alias.asname or alias.name)
        files[rel] = {
            "mtime": path.stat().st_mtime,
            "size": path.stat().st_size,
            "classes": classes,
            "functions": functions,
            "imports": sorted(set(imports)),
            "imported_names": sorted(set(bound_names)),
        }
    return {
        "version": INDEX_VERSION,
        "root": str(root),
        "built_at": time.time(),
        "files": files,
        "errors": sorted(errors),
    }


@dataclass(frozen=True)
class Definition:
    """تعريف واحد في الفهرس — ملفه وسطره ونوعه وتوقيعه."""

    file: str
    name: str
    kind: str  # "class" | "function" | "method"
    line: int
    signature: str


class CodeIndex:
    """فهرس جاهز للاستعلام — قراءة فقط، بلا حالة شبكية ولا تنفيذ."""

    def __init__(self, data: dict[str, Any]) -> None:
        if data.get("version") != INDEX_VERSION:
            raise ValueError(
                f"نسخة فهرس غير مفهومة: {data.get('version')} (المطلوبة: {INDEX_VERSION})")
        self._data = data
        self._files: dict[str, Any] = data.get("files", {})

    # ── الدورة الكاملة ────────────────────────────────────────────────
    @classmethod
    def build(cls, root: Path) -> "CodeIndex":
        return cls(build_index(root))

    @classmethod
    def load(cls, path: Path) -> "CodeIndex":
        """حمّل من القرص — الملف التالف أو الناقص يرفع ``ValueError`` صريحاً."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"تعذّر تحميل الفهرس: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or "files" not in data:
            raise ValueError("الفهرس بُهتان: لا حقل files")
        return cls(data)

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._data, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8")
        return path

    # ── الصحة ─────────────────────────────────────────────────────────
    def is_stale(self, root: Path) -> bool:
        """تغيّر ملف واحد (mtime أو حذف أو ولادة جديدة) ⇒ الفهرس باهت."""
        root = Path(root).resolve()
        known = set(self._files)
        current: dict[str, float] = {}
        for path in iter_python_files(root):
            rel = path.relative_to(root).as_posix()
            current[rel] = path.stat().st_mtime
        if known != set(current):
            return True
        return any(current[rel] != self._files[rel].get("mtime") for rel in current)

    @property
    def file_count(self) -> int:
        return len(self._files)

    @property
    def errors(self) -> list[str]:
        return list(self._data.get("errors", []))

    # ── الاستعلام ─────────────────────────────────────────────────────
    def lookup(self, name: str) -> list[Definition]:
        """كل تعريفات الاسم — مرتّبة (ملف ثم سطر) حتمياً."""
        if not name or not name.isidentifier():
            return []
        found: list[Definition] = []
        for rel in sorted(self._files):
            entry = self._files[rel]
            for cls in entry.get("classes", []):
                if cls["name"] == name:
                    found.append(Definition(rel, name, "class", cls["line"], name))
                for method in cls.get("methods", []):
                    if method == name:
                        found.append(Definition(
                            rel, name, "method", cls["line"], f"{cls['name']}.{name}"))
            for func in entry.get("functions", []):
                if func["name"] == name:
                    found.append(Definition(
                        rel, name, "function", func["line"],
                        func.get("signature", name)))
        return found

    def refs(self, name: str) -> list[str]:
        """الملفات التي تستورد الاسم أو تعرّفه — مرتّبة بلا تكرار.

        المستورد يُرى بالاسم المُربوط (``from m import x`` يربط ``x``)
        وبالمسار الكامل (``import a.b.c`` يربط ``c`` كمسار) — كلاهما يُحتسب.
        """
        importers: set[str] = set()
        for rel in sorted(self._files):
            entry = self._files[rel]
            if name in entry.get("imported_names", []):
                importers.add(rel)
                continue
            for module in entry.get("imports", []):
                if module == name or module.endswith("." + name):
                    importers.add(rel)
                    break
        definers = {d.file for d in self.lookup(name)}
        return sorted(importers | definers)

    def slice_for(self, name: str, max_defs: int = 6, max_refs: int = 8) -> str:
        """شريحة سياق مضغوطة جاهزة للبرومبت — تعريفات ثم مستوردون.

        الأسماء غير المفهومة تعيد نصاً معلناً بدل فراغ — الفحص يرى الحقيقة.
        """
        if not name or not name.isidentifier():
            return f"# شريحة فارغة: الاسم غير صالح ({name!r})"
        defs = self.lookup(name)
        refs = self.refs(name)
        if not defs and not refs:
            return f"# لا أثر للاسم في الفهرس: {name}"
        lines = [f"# شريحة {name} — {len(defs)} تعريفاً، {len(refs)} ملفاً مسحوباً"]
        for d in defs[:max_defs]:
            lines.append(f"- {d.kind} {d.signature} ← {d.file}:{d.line}")
        if len(defs) > max_defs:
            lines.append(f"- … {len(defs) - max_defs} تعريفاً آخر مقصوصاً")
        others = [r for r in refs if r not in {d.file for d in defs}]
        for r in others[:max_refs]:
            lines.append(f"- مستورد ← {r}")
        if len(others) > max_refs:
            lines.append(f"- … {len(others) - max_refs} ملفاً آخر مقصوصاً")
        return "\n".join(lines)


#: اسم متوافق قديماً — ``slice_for(index, name)`` يستدعي الشريحة مباشرة.
def slice_for(index: CodeIndex, name: str, **kw: Any) -> str:
    return index.slice_for(name, **kw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code-index", description="فهرس الذكاء — بناء واستعلام بلا شبكة")
    parser.add_argument("command", choices=("build", "lookup", "refs", "slice"))
    parser.add_argument("name", nargs="?", default=None)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default=None, help="مسار حفظ/تحميل الفهرس")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.command == "build":
        index = CodeIndex.build(root)
        if args.out:
            saved = index.save(Path(args.out))
            print(f"index: {saved} ({index.file_count} ملفاً، {len(index.errors)} خطأ)")
        else:
            print(index.snapshot_json() if hasattr(index, "snapshot_json") else
                  json.dumps(index._data, ensure_ascii=False, sort_keys=True, indent=1))
        return 0

    if not args.name:
        parser.error(f"الأمر {args.command} يحتاج اسم رمز")
    index = CodeIndex.load(Path(args.out)) if args.out else CodeIndex.build(root)
    if args.command == "lookup":
        for d in index.lookup(args.name):
            print(f"{d.kind}\t{d.file}:{d.line}\t{d.signature}")
    elif args.command == "refs":
        for r in index.refs(args.name):
            print(r)
    else:
        print(index.slice_for(args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
