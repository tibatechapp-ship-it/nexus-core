"""Repo map — stage 1 of the engine: modules, imports and LOC via AST.

خريطة البنية (مهمة M2.1): تُبنى بـ ast لا بالنصوص، بلا قراءة شبكة،
وترتيب ثابت حتى تكون خطة الإصلاح قابلة لإعادة الإنتاج.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 512 * 1024  # skip generated dumps, keep the map cheap
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "novamind"}


@dataclass
class ModuleInfo:
    """One importable module: where it lives, what it pulls, how big it is."""

    path: str                     # repo-relative
    name: str                     # dotted module name
    doc: str                      # first line of the docstring, "" if none
    imports: list = field(default_factory=list)
    loc: int = 0


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def parse_module(path: Path, rel: Path) -> ModuleInfo:
    """Parse one Python file into a ModuleInfo (doc, imports, LOC)."""
    source = path.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", "replace")
    tree = ast.parse(source)
    doc = ast.get_docstring(tree) or ""
    imports: list = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return ModuleInfo(
        path=rel.as_posix(),
        name=_module_name(rel),
        doc=doc.splitlines()[0].strip() if doc else "",
        imports=sorted(set(imports)),
        loc=len(source.splitlines()),
    )


def analyze_repo(root: Path) -> dict:
    """Map every Python module under ``root`` (stable order, no network)."""
    modules: list = []
    for path in sorted(Path(root).rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        try:
            modules.append(asdict(parse_module(path, rel)))
        except SyntaxError:
            modules.append(
                {
                    "path": rel.as_posix(),
                    "name": _module_name(rel),
                    "doc": "",
                    "imports": [],
                    "loc": len(path.read_bytes().splitlines()),
                    "syntax_error": True,
                }
            )
    total_loc = sum(m["loc"] for m in modules)
    external = sorted({i for m in modules for i in m["imports"]})
    return {
        "modules": modules,
        "total_loc": total_loc,
        "external_imports": external,
        "summary": f"{len(modules)} modules, {total_loc} LOC",
    }
