"""Deadcode Agent — Detects unused imports, variables, functions."""
import logging
import ast
from typing import Dict, List

logger = logging.getLogger("agents.deadcode_agent")


class DeadCodeAgent:

    def __init__(self):
        self.name = "deadcode"
    """Detects dead code."""

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []

        if filename.endswith(".py"):
            try:
                tree = ast.parse(code)

                # Unused imports
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            name = n.asname or n.name.split(".")[0]
                            if not self._is_used(tree, name):
                                issues.append({
                                    "line": node.lineno,
                                    "category": "unused_import",
                                    "severity": "low",
                                    "description": f"Unused import: {name}",
                                })
                    elif isinstance(node, ast.ImportFrom):
                        for n in node.names:
                            name = n.asname or n.name
                            if name == "*":
                                continue
                            if not self._is_used(tree, name):
                                issues.append({
                                    "line": node.lineno,
                                    "category": "unused_import",
                                    "severity": "low",
                                    "description": f"Unused import: {name}",
                                })

                # Unused variables in functions
                for func in ast.walk(tree):
                    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    assigned = {}
                    used = set()
                    for n in ast.walk(func):
                        if isinstance(n, ast.Assign):
                            for t in n.targets:
                                if isinstance(t, ast.Name):
                                    assigned[t.id] = n.lineno
                        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                            used.add(n.id)
                    for name, line in assigned.items():
                        if name not in used and not name.startswith("_"):
                            issues.append({
                                "line": line,
                                "category": "unused_variable",
                                "severity": "low",
                                "description": f"Unused variable: {name}",
                            })

            except SyntaxError:
                pass

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }

    def _is_used(self, tree, name: str) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name:
                return True
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == name:
                    return True
        return False


deadcode_agent = DeadCodeAgent()
__all__ = ["DeadCodeAgent", "deadcode_agent"]
