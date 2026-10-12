"""
Error Detector v1 — 5-layer error detection (safe quotes version).
Never modifies code — only detects and reports.
"""
import ast
import re
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("core.analysis.error_detector")


class ErrorDetector:
    """Multi-layer error detection."""

    # ═══════════════════════════════════════════════════════════
    #  L1 — Regex patterns (no nested quotes)
    # ═══════════════════════════════════════════════════════════
    REGEX_RULES = {
        "python": [
            (r"\bprint\s+[^(]", "SyntaxError", "print() needs parentheses in Python 3"),
            (r"\bexcept\s*:", "BareExcept", "bare except: catches all exceptions"),
            (r"\beval\s*\(", "SecurityRisk", "eval() — security risk"),
            (r"\bexec\s*\(", "SecurityRisk", "exec() — security risk"),
            (r"==\s*None", "CompareNone", "use (is None) instead of (== None)"),
            (r"!=\s*None", "CompareNone", "use (is not None) instead of (!= None)"),
            (r"\bTODO\b|\bFIXME\b", "Note", "TODO/FIXME comment"),
        ],
        "javascript": [
            (r"\bvar\s+\w", "StyleWarning", "use let or const instead of var"),
            (r"[^=!<>]==[^=]", "StyleWarning", "use (===) instead of (==)"),
            (r"[^=!<>]!=[^=]", "StyleWarning", "use (!==) instead of (!=)"),
            (r"\bconsole\.log\s*\(", "Note", "console.log() in production"),
        ],
        "typescript": [
            (r":\s*any\b", "TypeWarning", "avoid any — use specific types"),
            (r"\bas\s+any\b", "TypeWarning", "cast to any — weakens types"),
            (r"@ts-ignore", "TypeWarning", "@ts-ignore hides type errors"),
            (r"@ts-nocheck", "TypeError", "@ts-nocheck disables checking"),
        ],
    }

    @classmethod
    def regex_scan(cls, code: str, lang: str) -> List[Dict]:
        rules = cls.REGEX_RULES.get(lang, [])
        results = []
        for i, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//")):
                continue
            for pattern, etype, msg in rules:
                try:
                    if re.search(pattern, line):
                        results.append({
                            "layer": "L1-regex",
                            "line": i,
                            "type": etype,
                            "message": msg,
                            "snippet": stripped[:100],
                            "severity": cls._severity(etype),
                        })
                except re.error:
                    continue
        return results

    # ═══════════════════════════════════════════════════════════
    #  L2 — Python AST analysis
    # ═══════════════════════════════════════════════════════════
    @classmethod
    def ast_scan(cls, code: str) -> List[Dict]:
        results = []
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return [{
                "layer": "L2-ast",
                "line": e.lineno or 0,
                "type": "SyntaxError",
                "message": str(e.msg),
                "severity": "error",
            }]

        for node in ast.walk(tree):
            # Unused imports
            if isinstance(node, ast.Import):
                for n in node.names:
                    name = n.asname or n.name.split(".")[0]
                    if not cls._is_used(tree, name):
                        results.append({
                            "layer": "L2-ast",
                            "line": node.lineno,
                            "type": "UnusedImport",
                            "message": f"'{name}' imported but not used",
                            "severity": "warning",
                        })

            # Long functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    body_lines = node.end_lineno - node.lineno
                    if body_lines > 50:
                        results.append({
                            "layer": "L2-ast",
                            "line": node.lineno,
                            "type": "LongFunction",
                            "message": f"'{node.name}' is {body_lines} lines long",
                            "severity": "note",
                        })

                # Too many args
                if len(node.args.args) > 5:
                    results.append({
                        "layer": "L2-ast",
                        "line": node.lineno,
                        "type": "TooManyArgs",
                        "message": f"'{node.name}' has {len(node.args.args)} args",
                        "severity": "note",
                    })

                # Mutable default arguments
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        results.append({
                            "layer": "L2-ast",
                            "line": node.lineno,
                            "type": "MutableDefault",
                            "message": f"'{node.name}' has mutable default arg",
                            "severity": "warning",
                        })

        return results

    @staticmethod
    def _is_used(tree: ast.AST, name: str) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name:
                return True
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == name):
                return True
        return False

    # ═══════════════════════════════════════════════════════════
    #  L3 — Import resolution (checks if module is installed)
    # ═══════════════════════════════════════════════════════════
    @classmethod
    def import_check(cls, code: str) -> List[Dict]:
        results = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return results

        stdlib = {"os", "sys", "json", "re", "time", "datetime", "pathlib",
                  "typing", "logging", "subprocess", "shutil", "tempfile",
                  "ast", "collections", "itertools", "functools", "math",
                  "random", "hashlib", "base64", "io", "csv"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    base = n.name.split(".")[0]
                    if base in stdlib:
                        continue
                    if not cls._module_available(base):
                        results.append({
                            "layer": "L3-import",
                            "line": node.lineno,
                            "type": "MissingImport",
                            "message": f"module '{base}' not installed",
                            "severity": "error",
                        })

            elif isinstance(node, ast.ImportFrom) and node.module:
                base = node.module.split(".")[0]
                if base in stdlib:
                    continue
                if not cls._module_available(base):
                    results.append({
                        "layer": "L3-import",
                        "line": node.lineno,
                        "type": "MissingImport",
                        "message": f"module '{base}' not installed",
                        "severity": "error",
                    })
        return results

    @staticmethod
    def _module_available(name: str) -> bool:
        import importlib.util
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    # ═══════════════════════════════════════════════════════════
    #  L4 — Unused variables
    # ═══════════════════════════════════════════════════════════
    @classmethod
    def unused_vars(cls, code: str) -> List[Dict]:
        results = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return results

        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assigned = {}
            used = set()

            for node in ast.walk(func):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            assigned[t.id] = node.lineno
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    used.add(node.id)

            for name, line in assigned.items():
                if name not in used and not name.startswith("_"):
                    results.append({
                        "layer": "L4-unused",
                        "line": line,
                        "type": "UnusedVariable",
                        "message": f"'{name}' assigned but never used",
                        "severity": "warning",
                    })
        return results

    # ═══════════════════════════════════════════════════════════
    #  L5 — Complexity (branches per function)
    # ═══════════════════════════════════════════════════════════
    @classmethod
    def complexity(cls, code: str) -> List[Dict]:
        results = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return results

        branch_types = (ast.If, ast.For, ast.While, ast.ExceptHandler,
                        ast.With, ast.Assert)

        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            branches = sum(1 for n in ast.walk(func) if isinstance(n, branch_types))
            for n in ast.walk(func):
                if isinstance(n, ast.BoolOp):
                    branches += len(n.values) - 1

            if branches > 10:
                results.append({
                    "layer": "L5-complexity",
                    "line": func.lineno,
                    "type": "HighComplexity",
                    "message": f"'{func.name}' complexity = {branches}",
                    "severity": "warning",
                })
        return results

    # ═══════════════════════════════════════════════════════════
    #  Main API
    # ═══════════════════════════════════════════════════════════
    @classmethod
    def detect(cls, code: str, filename: str = "", lang: str = None) -> Dict:
        if lang is None:
            ext = Path(filename).suffix.lower()
            lang = {".py": "python", ".js": "javascript",
                    ".ts": "typescript", ".tsx": "typescript",
                    ".jsx": "javascript"}.get(ext, "python")

        all_issues = []
        all_issues += cls.regex_scan(code, lang)

        if lang == "python":
            all_issues += cls.ast_scan(code)
            all_issues += cls.import_check(code)
            all_issues += cls.unused_vars(code)
            all_issues += cls.complexity(code)

        by_sev = {"error": 0, "warning": 0, "note": 0}
        for i in all_issues:
            by_sev[i.get("severity", "note")] += 1

        return {
            "ok": by_sev["error"] == 0,
            "language": lang,
            "file": filename,
            "total": len(all_issues),
            "by_severity": by_sev,
            "issues": all_issues,
        }

    @staticmethod
    def _severity(etype: str) -> str:
        if etype in ("SyntaxError", "TypeError", "SecurityRisk", "MissingImport"):
            return "error"
        if etype in ("StyleWarning", "TypeWarning", "BareExcept", "UnusedImport",
                     "CompareNone", "MutableDefault"):
            return "warning"
        return "note"


error_detector = ErrorDetector()
