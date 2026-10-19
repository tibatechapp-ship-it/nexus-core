#!/usr/bin/env python3
"""Detect environment reads that happen at *import time*.

A module-scope (or class-body) ``os.getenv`` / ``os.environ`` access is
evaluated the moment the module is imported — before any caller can inject a
configuration. That is a footgun for BYOK connectors: it bakes a value into
the module and can leak/short-circuit runtime config.

This tool scans the packages that are imported by the running service and
flags every env read that is **not** inside a function (i.e. import-time).

Usage:
    python3 tools/detect_env_imports.py            # scan default roots
    python3 tools/detect_env_imports.py connectors # scan a specific dir

Exit code is 0 always (it is a report), unless --strict is passed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Directories that hold code imported by the live service.
DEFAULT_ROOTS = ("connectors", "hyper_app", "src")

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _env_access(node: ast.AST) -> bool:
    """True if ``node`` is an ``os.getenv(...)`` call or an ``os.environ`` use."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "getenv":
            return getattr(func.value, "id", None) == "os"
    if isinstance(node, ast.Attribute):
        # os.environ  (covers os.environ.get(...) and os.environ["X"])
        return getattr(node.value, "id", None) == "os" and node.attr == "environ"
    if isinstance(node, ast.Subscript):  # os.environ["X"]
        base = node.value
        return isinstance(base, ast.Attribute) and base.attr == "environ"
    return False


def _has_function_ancestor(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Walk the parent chain; True if the node lives inside a function/lambda."""
    cur: ast.AST | None = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, _FUNC_NODES):
            return True
        cur = parents.get(id(cur))
    return False


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, snippet_kind)`` for every import-time env read."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [(exc.lineno or 0, f"syntax error: {exc.msg}")]

    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if _env_access(node) and not _has_function_ancestor(node, parents):
            kind = "os.getenv" if isinstance(node, ast.Call) else "os.environ"
            findings.append((node.lineno, kind))
    return findings


def scan_root(root: Path) -> int:
    """Scan every ``*.py`` under ``root``; print findings. Return total count."""
    total = 0
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        findings = scan_file(path)
        if findings:
            print(f"== {path} ==")
            for lineno, kind in findings:
                print(f"   line {lineno}: {kind} read at import time")
                total += 1
    return total


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("-")]
    roots = [Path(a) for a in args] or [Path(r) for r in DEFAULT_ROOTS]
    roots = [r for r in roots if r.exists()]

    if not roots:
        print("No scannable roots found (looked for: " + ", ".join(DEFAULT_ROOTS) + ")")
        return 0

    total = sum(scan_root(r) for r in roots)
    if total == 0:
        print("OK — no import-time environment reads found.")
    else:
        print(f"\n{total} import-time env read(s) found.")
    return 1 if (strict and total) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
