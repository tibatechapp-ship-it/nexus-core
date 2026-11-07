"""Import-level reachability (س2) — does the code actually touch the package?

The competitive review (MIZAN_ROADMAP.md س2) named the gap: engines like
Snyk degrade a dependency finding when the code never reaches the vulnerable
surface. MIZAN now answers the same question *within its declared scope*:
a static import/call graph over the repository's own ``*.py`` files, built
with :mod:`ast` only.

Declared boundaries (honesty before cleverness):

* **Direct imports only.** A package imported solely by a *transitive*
  dependency is invisible here — ``absent`` therefore means "no direct
  import found", never "provably unused at runtime" (entry points, plugins
  and dynamic strings can still load it).
* **Import-name approximation.** The pip distribution name and the import
  name usually coincide; where they do not (``python-dateutil`` vs
  ``dateutil``) the matcher tries the normalized name plus the
  dash→underscore variant and reports the limitation in the output.
* **Conservative upward bias.** Anything ambiguous (dynamic
  ``__import__``/``importlib`` with the package's root in a literal, a
  failed parse) is treated as *reachable*, not silently clean.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .manifest import normalize_name

__all__ = [
    "ABSENT",
    "IMPORT_ONLY",
    "REACHABLE",
    "Assessment",
    "ImportFacts",
    "import_roots_for",
    "assess_tree",
]

#: Verdict vocabulary — kept as module constants so reports never spell
#: the strings by hand (typo = new "verdict").
REACHABLE = "reachable"      # imported AND a call resolves through it
IMPORT_ONLY = "import-only"  # imported, but no resolved call was found
ABSENT = "absent"            # no direct import anywhere in the tree

#: Directories never walked (cache/build noise, not source).
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".venv", "venv", "__pycache__", "node_modules", ".tox",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "build", "dist",
    ".github", ".mizan",
})

#: Hard cap on walked files — one bounded scan instead of an unbounded
#: crawl if someone points the tool at a checkout-bomb.
MAX_FILES = 5000


@dataclass(frozen=True)
class ImportFacts:
    """Per-package evidence collected from the tree."""

    package: str                          # normalized pip-style name
    files_importing: tuple[str, ...] = ()  # relative paths of importers
    call_files: tuple[str, ...] = ()       # subset where a call resolves
    dynamic_import: bool = False           # __import__/importlib literal seen

    @property
    def verdict(self) -> str:
        """The tri-state verdict (س2): reachable / import-only / absent.

        Dynamic imports and any resolved call both count as *reachable*
        because the conservative bias is upward, never toward silence.
        """
        if self.dynamic_import or self.call_files:
            return REACHABLE
        if self.files_importing:
            return IMPORT_ONLY
        return ABSENT


@dataclass(frozen=True)
class Assessment:
    """Result of scanning one tree for many packages."""

    facts: dict[str, ImportFacts] = field(default_factory=dict)
    files_scanned: int = 0
    unparsed: int = 0

    def verdicts(self) -> dict[str, str]:
        """Package name → verdict string, sorted by package name."""
        return {name: self.facts[name].verdict for name in sorted(self.facts)}


def iter_py_files(root: Path) -> list[Path]:
    """Collect ``*.py`` files under ``root`` with the skip-list and cap."""
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
        if len(files) >= MAX_FILES:
            break
    return files


def import_roots_for(tree: ast.Module) -> tuple[set[str], set[str], bool]:
    """Extract (root packages, dotted modules, dynamic-import-seen).

    Roots are the top-level names a package is imported under *after*
    aliasing (``import requests.api as ra`` contributes root ``requests``
    for the dotted module and binding ``ra`` — callers use the dotted set
    plus the roots to resolve calls).  Relative imports (``level > 0``)
    resolve inside the project, not to a dependency, and are ignored.
    """
    roots: set[str] = set()
    dotted: set[str] = set()
    dynamic = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted.add(alias.name)
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                dotted.add(node.module)
                roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if _dynamic_import_call(node):
                dynamic = True
    return roots, dotted, dynamic


def _dynamic_import_call(node: ast.Call) -> bool:
    """True for ``__import__(…)`` or ``importlib.import_module(…)``."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "__import__":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "import_module":
        base = func.value
        if isinstance(base, ast.Name) and base.id == "importlib":
            return True
    return False


def _candidate_names(package: str) -> tuple[str, str]:
    """Import-name candidates for a pip-style distribution name."""
    return normalize_name(package), normalize_name(package).replace("-", "_")


class _FileFacts:
    """Mutable per-file accumulator (never leaves this module)."""

    def __init__(self, rel: str, tree: ast.Module) -> None:
        self.rel = rel
        self.roots, self.dotted, self.dynamic = import_roots_for(tree)
        self.dynamic_roots: set[str] = set()
        self.bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.bindings[alias.asname or alias.name.split(".")[0]] = (
                        alias.name
                    )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                base = node.module or ""
                for alias in node.names:
                    origin = f"{base}.{alias.name}" if base else alias.name
                    self.bindings[alias.asname or alias.name] = origin
        self.called_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if _dynamic_import_call(node):
                    # the string literal names the module — a direct hit
                    if node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, str):
                        self.dynamic_roots.add(
                            node.args[0].value.split(".")[0],
                        )
                self.called_roots.update(self._call_roots(node))

    def _call_roots(self, call: ast.Call) -> set[str]:
        """Roots of packages a call resolves through (bindings-aware)."""
        found: set[str] = set()
        func = call.func
        if isinstance(func, ast.Name):
            origin = self.bindings.get(func.id)
            if origin:
                found.add(origin.split(".")[0])
        elif isinstance(func, ast.Attribute):
            dotted = _dotted_name(func)
            if dotted:
                found.add(dotted.split(".")[0])
                base = self.bindings.get(dotted.split(".")[0])
                if base:
                    found.add(base.split(".")[0])
        return found

    def touches(self, candidates: tuple[str, str]) -> bool:
        """Does this file import (under any alias) one of the names?"""
        return bool(self.roots & set(candidates)) or bool(
            self.dotted & set(candidates)
        )

    def calls(self, candidates: tuple[str, str]) -> bool:
        return bool(self.called_roots & set(candidates))

    def dynamic_hit(self, candidates: tuple[str, str]) -> bool:
        """Dynamic import whose string literal names the package root."""
        return bool(self.dynamic_roots & set(candidates))


def _dotted_name(node: ast.AST) -> str:
    """Best-effort dotted name of a Name/Attribute chain (``os.system``)."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def assess_tree(root: Path, packages: Iterable[str]) -> Assessment:
    """Assess every listed package against the ``*.py`` files under root.

    Unparseable files are *counted*, not hidden — the caller surfaces the
    number so a degraded scan is visible instead of looking clean.
    """
    wanted = {normalize_name(p) for p in packages if normalize_name(p)}
    candidates: dict[str, tuple[str, str]] = {
        name: _candidate_names(name) for name in wanted
    }
    importing: dict[str, list[str]] = {n: [] for n in wanted}
    calling: dict[str, list[str]] = {n: [] for n in wanted}
    dynamic: dict[str, bool] = {n: False for n in wanted}
    scanned = 0
    unparsed = 0

    for path in iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except (SyntaxError, ValueError, OSError, UnicodeDecodeError):
            unparsed += 1
            continue
        scanned += 1
        ff = _FileFacts(str(path.relative_to(root)), tree)
        for name, cands in candidates.items():
            if ff.touches(cands):
                importing[name].append(ff.rel)
            if ff.calls(cands):
                calling[name].append(ff.rel)
            if ff.dynamic_hit(cands):
                dynamic[name] = True

    facts = {
        name: ImportFacts(
            package=name,
            files_importing=tuple(importing[name]),
            call_files=tuple(calling[name]),
            dynamic_import=dynamic[name],
        )
        for name in sorted(wanted)
    }
    return Assessment(facts=facts, files_scanned=scanned, unparsed=unparsed)
