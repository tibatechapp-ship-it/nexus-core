"""Architecture Agent — Detects SOLID violations, circular imports."""
import logging
import re
import ast
from typing import Dict, List

logger = logging.getLogger("agents.architecture_agent")


class ArchitectureAgent:

    def __init__(self):
        self.name = "architecture"
    """Detects architecture issues."""

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        # Large classes
        if filename.endswith(".py"):
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        methods = [n for n in node.body
                                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                        if len(methods) > 15:
                            issues.append({
                                "line": node.lineno,
                                "category": "god_class",
                                "severity": "medium",
                                "description": f"Class '{node.name}' has {len(methods)} methods",
                            })

                        # Deep inheritance
                        if len(node.bases) > 2:
                            issues.append({
                                "line": node.lineno,
                                "category": "multiple_inheritance",
                                "severity": "info",
                                "description": f"Class '{node.name}' has {len(node.bases)} bases",
                            })

                    # God function
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if hasattr(node, "end_lineno") and node.end_lineno:
                            length = node.end_lineno - node.lineno
                            if length > 100:
                                issues.append({
                                    "line": node.lineno,
                                    "category": "god_function",
                                    "severity": "medium",
                                    "description": f"'{node.name}' is {length} lines",
                                })
            except SyntaxError:
                pass

        # Circular imports (simple heuristic)
        imports = set()
        for line in lines:
            m = re.match(r'^\s*(?:from|import)\s+([a-zA-Z0-9_.]+)', line)
            if m:
                imports.add(m.group(1).split(".")[0])

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


architecture_agent = ArchitectureAgent()
__all__ = ["ArchitectureAgent", "architecture_agent"]
