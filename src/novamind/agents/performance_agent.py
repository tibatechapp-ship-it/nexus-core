"""
Performance Agent — Detects performance issues and optimizations.
"""
import logging
import re
import ast
from typing import Dict, List

logger = logging.getLogger("agents.performance_agent")


class PerformanceAgent:

    def __init__(self):
        self.name = "performance"
    """Detects performance bottlenecks."""

    # Pattern-based (fast scan)
    PATTERNS = {
        "n_plus_one": {
            "python": [
                (r'for\s+\w+\s+in\s+[^:]+:\s+.*\.(query|filter|get)\s*\(', "N+1 query in loop"),
            ],
        },
        "inefficient_loop": {
            "any": [
                (r'for\s+\w+\s+in\s+range\s*\(\s*len\s*\(', "range(len(...)) — use enumerate"),
                (r'\.append\s*\([^)]*\)\s*$', "Append in tight loop — consider comprehension"),
            ],
        },
        "memory_issue": {
            "any": [
                (r'\[\s*\]\s*\*\s*\d{6,}', "Large list multiplication"),
                (r'read\s*\(\s*\)', "read() entire file — use streaming"),
                (r'\.readlines\s*\(\s*\)', "readlines() — iterate directly"),
            ],
        },
        "sync_in_async": {
            "python": [
                (r'async\s+def[^:]+:\s+(?:(?!await).)*?requests\.(get|post)', "sync requests in async — use aiohttp"),
                (r'async\s+def[^:]+:\s+(?:(?!await).)*?time\.sleep', "time.sleep in async — use asyncio.sleep"),
            ],
        },
        "string_concat": {
            "any": [
                (r'\w+\s*\+=\s*["\']', "+= string — consider list + join"),
                (r'["\'][^"\']*["\']\s*\+\s*["\']', "String concat — use f-string or format"),
            ],
        },
        "regex_in_loop": {
            "any": [
                (r'for\s+\w+\s+in[^:]+:\s+.*re\.(compile|match|search)', "regex in loop — compile outside"),
            ],
        },
        "expensive_copy": {
            "any": [
                (r'copy\.deepcopy\s*\(', "deepcopy is expensive — consider lighter"),
                (r'\.copy\s*\(\s*\).*in\s+for', ".copy in loop — batch"),
            ],
        },
    }

    def detect_lang(self, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "py":
            return "python"
        if ext in ("js", "jsx", "ts", "tsx"):
            return "javascript"
        return "any"

    def analyze(self, code: str, filename: str = "code.py") -> Dict:
        """Analyze for performance issues."""
        if not code or not code.strip():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        lang = self.detect_lang(filename)
        issues = []
        lines = code.split("\n")

        # Pattern scan
        for category, langs in self.PATTERNS.items():
            patterns = langs.get(lang, []) + langs.get("any", [])
            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                except re.error:
                    continue

                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith(("#", "//")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "severity": "medium",
                            "category": category,
                            "description": desc,
                            "snippet": stripped[:100],
                        })

        # AST-based for Python
        if lang == "python":
            issues.extend(self._python_ast_checks(code))

        # Deduplicate
        seen = set()
        unique = []
        for issue in issues:
            key = (issue["line"], issue["category"])
            if key not in seen:
                seen.add(key)
                unique.append(issue)

        verdict = "issues" if unique else "ok"

        return {
            "ok": verdict == "ok",
            "verdict": verdict,
            "language": lang,
            "total": len(unique),
            "by_severity": {
                "critical": 0,
                "high": sum(1 for i in unique if i["severity"] == "high"),
                "medium": sum(1 for i in unique if i["severity"] == "medium"),
            },
            "issues": unique,
        }

    def _python_ast_checks(self, code: str) -> List[Dict]:
        """AST checks for complex patterns."""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for func in ast.walk(tree):
            if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Count nested loops
                nested_loops = 0
                for node in ast.walk(func):
                    if isinstance(node, (ast.For, ast.While)):
                        nested_loops += 1
                        # Check for nested loops inside
                        for inner in ast.walk(node):
                            if inner is not node and isinstance(inner, (ast.For, ast.While)):
                                issues.append({
                                    "line": node.lineno,
                                    "severity": "medium",
                                    "category": "nested_loop",
                                    "description": "Nested loop — likely O(n²)",
                                    "snippet": f"in {func.name}()",
                                })
                                break

                # Function too long
                if hasattr(func, "end_lineno") and func.end_lineno:
                    length = func.end_lineno - func.lineno
                    if length > 50:
                        issues.append({
                            "line": func.lineno,
                            "severity": "medium",
                            "category": "long_function",
                            "description": f"Function too long ({length} lines)",
                            "snippet": func.name,
                        })

        return issues

    def report(self, result: Dict) -> str:
        """Human-readable report."""
        if result.get("verdict") == "ok":
            return "✅ لا توجد مشاكل أداء"

        lines = [f"⚡ تقرير الأداء ({result['total']} مشكلة)"]
        lines.append("")

        by_sev = {"high": "🔴", "medium": "🟡", "critical": "🚨"}

        for severity in ["critical", "high", "medium"]:
            sev_issues = [i for i in result["issues"] if i["severity"] == severity]
            if not sev_issues:
                continue
            lines.append(f"{by_sev.get(severity, '•')} {severity.upper()}: {len(sev_issues)}")
            for issue in sev_issues[:10]:
                lines.append(f"   L{issue['line']}: {issue['description']}")
            lines.append("")

        return "\n".join(lines)


performance_agent = PerformanceAgent()
__all__ = ["PerformanceAgent", "performance_agent"]
