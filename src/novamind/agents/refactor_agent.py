"""
Refactor Agent — Suggests refactoring opportunities.
Detects: duplication, long functions, magic numbers, many args.
"""
import logging
import re
import ast
from typing import Dict, List
from collections import Counter

logger = logging.getLogger("agents.refactor_agent")


class RefactorAgent:

    def __init__(self):
        self.name = "refactor"
    """Suggests refactoring opportunities."""

    def analyze(self, code: str, filename: str = "code.py") -> Dict:
        """Find refactoring opportunities."""
        if not code or not code.strip():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        lang = "python" if filename.endswith(".py") else "javascript"
        issues = []

        if lang == "python":
            issues.extend(self._python_refactors(code))
        else:
            issues.extend(self._js_refactors(code))

        return {
            "ok": len(issues) == 0,
            "verdict": "issues" if issues else "ok",
            "language": lang,
            "total": len(issues),
            "issues": issues,
        }

    def _python_refactors(self, code: str) -> List[Dict]:
        """Python-specific refactor checks."""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 1. Duplication (heuristic)
        lines = [l.strip() for l in code.split("\n")
                 if l.strip() and not l.strip().startswith("#")]
        counter = Counter(lines)
        duplicated = [(line, count) for line, count in counter.items()
                      if count >= 3 and len(line) > 20]

        if duplicated:
            issues.append({
                "line": 0,
                "type": "duplication",
                "severity": "medium",
                "description": f"{len(duplicated)} duplicated lines — extract function",
                "examples": [d[0][:60] for d in duplicated[:3]],
            })

        # 2. Long functions / many args
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    length = node.end_lineno - node.lineno
                    if length > 40:
                        issues.append({
                            "line": node.lineno,
                            "type": "long_function",
                            "severity": "medium",
                            "description": f"'{node.name}' is {length} lines — split it",
                        })
                if len(node.args.args) > 5:
                    issues.append({
                        "line": node.lineno,
                        "type": "many_args",
                        "severity": "low",
                        "description": f"'{node.name}' has {len(node.args.args)} args — use dataclass",
                    })

        # 3. Magic numbers
        magic_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if node.value > 100 and node.value not in (200, 1000, 1024):
                    issues.append({
                        "line": node.lineno,
                        "type": "magic_number",
                        "severity": "info",
                        "description": f"Magic number {node.value} — use named constant",
                    })
                    magic_count += 1
                    if magic_count >= 3:
                        break

        # 4. Deep nesting
        for func in ast.walk(tree):
            if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                max_depth = self._max_nesting_depth(func)
                if max_depth >= 4:
                    issues.append({
                        "line": func.lineno,
                        "type": "deep_nesting",
                        "severity": "medium",
                        "description": f"'{func.name}' has {max_depth} levels — simplify",
                    })

        return issues

    def _max_nesting_depth(self, node, depth: int = 0) -> int:
        """Compute max nesting depth of a node."""
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While,
                                   ast.With, ast.Try)):
                max_depth = max(max_depth, self._max_nesting_depth(child, depth + 1))
            else:
                max_depth = max(max_depth, self._max_nesting_depth(child, depth))
        return max_depth

    def _js_refactors(self, code: str) -> List[Dict]:
        """JS/TS refactor checks."""
        issues = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                issues.append({
                    "line": i,
                    "type": "long_line",
                    "severity": "low",
                    "description": f"Line too long ({len(line)} chars)",
                })
            if re.search(r'\bvar\s+', line):
                issues.append({
                    "line": i,
                    "type": "var_usage",
                    "severity": "low",
                    "description": "var — use let/const",
                })

        return issues

    def report(self, result: Dict) -> str:
        """Human-readable report."""
        if result.get("verdict") == "ok":
            return "✅ الكود نظيف — لا يحتاج إعادة هيكلة"

        lines = [f"♻️  تقرير إعادة الهيكلة ({result['total']} فرصة)"]
        lines.append("")

        by_type = {}
        for issue in result["issues"]:
            t = issue.get("type", "other")
            by_type.setdefault(t, []).append(issue)

        icons = {
            "duplication": "📋",
            "long_function": "📏",
            "many_args": "🔢",
            "magic_number": "🔮",
            "deep_nesting": "🏔️",
            "long_line": "📐",
            "var_usage": "📦",
        }

        for t, items in by_type.items():
            lines.append(f"{icons.get(t, '•')} {t}: {len(items)}")
            for issue in items[:3]:
                lines.append(f"   L{issue['line']}: {issue['description']}")
            lines.append("")

        return "\n".join(lines)


refactor_agent = RefactorAgent()
__all__ = ["RefactorAgent", "refactor_agent"]
