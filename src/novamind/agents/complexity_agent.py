"""Complexity Agent — Detects high cyclomatic complexity."""
import logging
import ast
from typing import Dict, List

logger = logging.getLogger("agents.complexity_agent")


class ComplexityAgent:

    def __init__(self):
        self.name = "complexity"
    """Detects cyclomatic complexity issues."""

    THRESHOLD_WARN = 10
    THRESHOLD_ERROR = 20

    def _branch_count(self, node) -> int:
        count = 0
        for n in ast.walk(node):
            if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                              ast.With, ast.Assert)):
                count += 1
            elif isinstance(n, ast.BoolOp):
                count += len(n.values) - 1
        return count

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []

        if filename.endswith(".py"):
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        cc = self._branch_count(node) + 1
                        if cc >= self.THRESHOLD_ERROR:
                            issues.append({
                                "line": node.lineno,
                                "category": "very_high_complexity",
                                "severity": "high",
                                "description": f"'{node.name}' complexity = {cc}",
                            })
                        elif cc >= self.THRESHOLD_WARN:
                            issues.append({
                                "line": node.lineno,
                                "category": "high_complexity",
                                "severity": "medium",
                                "description": f"'{node.name}' complexity = {cc}",
                            })
            except SyntaxError:
                pass

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


complexity_agent = ComplexityAgent()
__all__ = ["ComplexityAgent", "complexity_agent"]
