"""
Documentation Agent — Auto-generates and checks docstrings.
"""
import logging
import ast
from typing import Dict, List

logger = logging.getLogger("agents.documentation_agent")


class DocumentationAgent:

    def __init__(self):
        self.name = "documentation"
    """Analyzes and improves code documentation."""

    def analyze(self, code: str, filename: str = "code.py") -> Dict:
        """Find undocumented functions/classes."""
        if not code or not code.strip():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        lang = "python" if filename.endswith(".py") else "other"
        issues = []

        if lang == "python":
            issues = self._check_python_docs(code)

        return {
            "ok": len(issues) == 0,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }

    def _check_python_docs(self, code: str) -> List[Dict]:
        """Check Python for missing docstrings."""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            # Check functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    docstring = ast.get_docstring(node)
                    if not docstring:
                        issues.append({
                            "line": node.lineno,
                            "type": "missing_docstring",
                            "severity": "low",
                            "description": f"Function '{node.name}' has no docstring",
                            "name": node.name,
                        })
                    elif len(docstring) < 20:
                        issues.append({
                            "line": node.lineno,
                            "type": "short_docstring",
                            "severity": "info",
                            "description": f"'{node.name}' docstring is very short ({len(docstring)} chars)",
                            "name": node.name,
                        })

            # Check classes
            if isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    docstring = ast.get_docstring(node)
                    if not docstring:
                        issues.append({
                            "line": node.lineno,
                            "type": "missing_docstring",
                            "severity": "low",
                            "description": f"Class '{node.name}' has no docstring",
                            "name": node.name,
                        })

        return issues

    def generate_docstring(self, func_name: str, signature: str = "",
                            body: str = "", use_llm: bool = True) -> str:
        """Generate docstring for a function."""
        # Basic fallback (no LLM)
        basic = f'"""\n    {func_name} — TODO: add description\n    """'

        if not use_llm:
            return basic

        try:
            from novamind.core.providers.orchestrator import orchestrator
        except ImportError:
            return basic

        prompt = f"""اكتب docstring مختصر للدالة التالية.
أعد فقط الـ docstring بصيغة Python triple quotes.

```python
def {func_name}{signature}:
{body[:500]}
```"""

        try:
            result = orchestrator.call(prompt, task="fast", max_tokens=200)
            if result.get("ok"):
                text = result["text"].strip()
                # Strip existing quotes
                text = text.strip('"').strip("'").strip()
                return f'"""\n    {text}\n    """'
        except Exception:
            pass

        return basic

    def report(self, result: Dict) -> str:
        """Human-readable report."""
        if result.get("verdict") == "ok":
            return "✅ التوثيق مكتمل"

        lines = [f"📚 تقرير التوثيق ({result['total']} مشكلة)"]
        lines.append("")

        by_type = {}
        for issue in result["issues"]:
            t = issue.get("type", "other")
            by_type.setdefault(t, []).append(issue)

        for t, items in by_type.items():
            lines.append(f"• {t}: {len(items)}")
            for issue in items[:5]:
                lines.append(f"   L{issue['line']}: {issue['description']}")

        return "\n".join(lines)


documentation_agent = DocumentationAgent()
__all__ = ["DocumentationAgent", "documentation_agent"]
