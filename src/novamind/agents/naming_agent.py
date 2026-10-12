"""Naming Agent — Detects bad naming conventions."""
import logging
import re
import ast
from typing import Dict, List

logger = logging.getLogger("agents.naming_agent")


class NamingAgent:

    def __init__(self):
        self.name = "naming"
    """Detects naming issues."""

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []

        # Try AST for Python
        if filename.endswith(".py"):
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if not re.match(r'^[a-z_][a-z0-9_]*$', node.name):
                            issues.append({
                                "line": node.lineno,
                                "category": "function_naming",
                                "severity": "low",
                                "description": f"Function '{node.name}' — use snake_case",
                            })
                    elif isinstance(node, ast.ClassDef):
                        if not re.match(r'^[A-Z][a-zA-Z0-9]*$', node.name):
                            issues.append({
                                "line": node.lineno,
                                "category": "class_naming",
                                "severity": "low",
                                "description": f"Class '{node.name}' — use PascalCase",
                            })
                    elif isinstance(node, ast.Name):
                        if node.id in ("data", "temp", "tmp", "foo", "bar", "x", "y"):
                            issues.append({
                                "line": node.lineno,
                                "category": "vague_name",
                                "severity": "info",
                                "description": f"Vague name '{node.id}'",
                            })
            except SyntaxError:
                pass

        # Regex fallback
        lines = code.split("\n")
        for i, line in enumerate(lines, 1):
            if re.search(r'\bdef\s+[A-Z][a-zA-Z]*', line):
                issues.append({
                    "line": i, "category": "function_naming",
                    "severity": "low",
                    "description": "Function should be snake_case",
                })
            if re.search(r'\bclass\s+[a-z]', line):
                issues.append({
                    "line": i, "category": "class_naming",
                    "severity": "low",
                    "description": "Class should be PascalCase",
                })
            if len(line.strip()) > 0 and re.search(r'\b[A-Z]{5,}\b', line):
                if not any(x in line for x in ["HTTP", "HTTPS", "URL", "API", "ID", "JSON", "XML"]):
                    issues.append({
                        "line": i, "category": "constant_naming",
                        "severity": "info",
                        "description": "All-caps identifier — verify intentional",
                    })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


naming_agent = NamingAgent()
__all__ = ["NamingAgent", "naming_agent"]
