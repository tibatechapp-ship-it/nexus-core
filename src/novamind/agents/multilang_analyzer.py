"""
MultiLanguage Analyzer - Supports Python, TypeScript, JavaScript, JSON, YAML, Markdown
"""
import re
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("agents.multilang")


# ═══════════════════════════════════════════════════════
#  Extension detection
# ═══════════════════════════════════════════════════════
def detect_language(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".html": "html",
        ".css": "css",
    }
    return mapping.get(ext, "unknown")


# ═══════════════════════════════════════════════════════
#  Python Checks
# ═══════════════════════════════════════════════════════
def check_python(code: str) -> Dict:
    issues = []

    # Syntax
    try:
        compile(code, "<test>", "exec")
    except SyntaxError as e:
        issues.append({
            "type": "syntax",
            "line": e.lineno or 0,
            "description": f"SyntaxError: {e.msg}",
            "severity": "error",
        })

    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Bare except
        if re.match(r'except\s*:', stripped):
            issues.append({
                "type": "style",
                "line": i,
                "description": "Bare 'except:' found - catch specific exceptions",
                "severity": "warning",
            })

        # print statements (should use logging in production)
        if "print(" in stripped and not stripped.startswith("#"):
            issues.append({
                "type": "style",
                "line": i,
                "description": "print() found - consider using logging",
                "severity": "info",
            })

        # TODO/FIXME
        if "TODO" in line or "FIXME" in line:
            issues.append({
                "type": "note",
                "line": i,
                "description": "TODO/FIXME marker found",
                "severity": "info",
            })

        # Division without zero check
        if re.search(r'/\s*\w+', stripped) and "if" not in stripped.lower():
            if "zero" not in stripped.lower() and "if not" not in stripped.lower():
                if "return" in stripped or "=" in stripped:
                    if any(kw in stripped for kw in ["/ ", "/=", "/x"]):
                        issues.append({
                            "type": "logic",
                            "line": i,
                            "description": "Division without zero check",
                            "severity": "warning",
                        })

    return {
        "language": "python",
        "issues": issues,
        "verdict": "ok" if not issues else ("broken" if any(
            i["severity"] == "error" for i in issues
        ) else "issues"),
    }


# ═══════════════════════════════════════════════════════
#  TypeScript/JavaScript Checks
# ═══════════════════════════════════════════════════════
def check_typescript(code: str, filename: str = "file.ts") -> Dict:
    issues = []
    lines = code.split("\n")

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # console.log
        if re.search(r'console\.(log|debug|info)', stripped):
            if not stripped.startswith("//"):
                issues.append({
                    "type": "style",
                    "line": i,
                    "description": "console.log() found - remove in production",
                    "severity": "warning",
                })

        # == instead of ===
        if re.search(r'[^=!<>]==[^=]', stripped) and "===" not in stripped:
            issues.append({
                "type": "style",
                "line": i,
                "description": "Use === instead of ==",
                "severity": "warning",
            })

        # != instead of !==
        if re.search(r'[^!]!=[^=]', stripped) and "!==" not in stripped:
            issues.append({
                "type": "style",
                "line": i,
                "description": "Use !== instead of !=",
                "severity": "warning",
            })

        # var instead of let/const
        if re.match(r'\s*var\s+', stripped):
            issues.append({
                "type": "style",
                "line": i,
                "description": "Use 'let' or 'const' instead of 'var'",
                "severity": "warning",
            })

        # any type (TypeScript)
        if filename.endswith((".ts", ".tsx")):
            if re.search(r':\s*any\b', stripped):
                issues.append({
                    "type": "style",
                    "line": i,
                    "description": "Avoid 'any' type - use specific types",
                    "severity": "warning",
                })

        # debugger
        if re.match(r'\s*debugger\s*;?', stripped):
            issues.append({
                "type": "logic",
                "line": i,
                "description": "debugger statement found - remove it",
                "severity": "error",
            })

        # TODO/FIXME
        if "TODO" in line or "FIXME" in line:
            issues.append({
                "type": "note",
                "line": i,
                "description": "TODO/FIXME marker found",
                "severity": "info",
            })

        # Missing await on Promise
        if "Promise" in stripped and "await" not in stripped and "then" not in stripped:
            if "=" in stripped and "return" in stripped:
                issues.append({
                    "type": "logic",
                    "line": i,
                    "description": "Possible missing await",
                    "severity": "warning",
                })

    # Basic syntax checks
    brackets = {"{": 0, "(": 0, "[": 0}
    for char in code:
        if char in brackets:
            brackets[char] += 1
        elif char == "}":
            brackets["{"] -= 1
        elif char == ")":
            brackets["("] -= 1
        elif char == "]":
            brackets["["] -= 1

    for bracket, count in brackets.items():
        if count != 0:
            issues.append({
                "type": "syntax",
                "line": 0,
                "description": f"Unbalanced '{bracket}' brackets (count: {count})",
                "severity": "error",
            })

    return {
        "language": "typescript" if filename.endswith((".ts", ".tsx")) else "javascript",
        "issues": issues,
        "verdict": "ok" if not issues else ("broken" if any(
            i["severity"] == "error" for i in issues
        ) else "issues"),
    }


# ═══════════════════════════════════════════════════════
#  JSON Checks
# ═══════════════════════════════════════════════════════
def check_json(code: str) -> Dict:
    issues = []
    try:
        json.loads(code)
    except json.JSONDecodeError as e:
        issues.append({
            "type": "syntax",
            "line": e.lineno,
            "description": f"JSON error: {e.msg}",
            "severity": "error",
        })
    return {
        "language": "json",
        "issues": issues,
        "verdict": "ok" if not issues else "broken",
    }


# ═══════════════════════════════════════════════════════
#  YAML Checks (basic)
# ═══════════════════════════════════════════════════════
def check_yaml(code: str) -> Dict:
    issues = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        # Tabs in YAML are forbidden
        if "\t" in line:
            issues.append({
                "type": "syntax",
                "line": i,
                "description": "Tabs not allowed in YAML - use spaces",
                "severity": "error",
            })
    return {
        "language": "yaml",
        "issues": issues,
        "verdict": "ok" if not issues else "issues",
    }


# ═══════════════════════════════════════════════════════
#  Markdown Checks
# ═══════════════════════════════════════════════════════
def check_markdown(code: str) -> Dict:
    issues = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Empty links
        if re.search(r'\[\]\([^)]*\)', stripped):
            issues.append({
                "type": "style",
                "line": i,
                "description": "Empty link text",
                "severity": "warning",
            })

        # Broken link syntax
        if re.search(r'\[[^\]]+\]\([^)]*$', stripped):
            issues.append({
                "type": "syntax",
                "line": i,
                "description": "Unclosed link",
                "severity": "warning",
            })

    return {
        "language": "markdown",
        "issues": issues,
        "verdict": "ok" if not issues else "issues",
    }


# ═══════════════════════════════════════════════════════
#  Universal Analyzer
# ═══════════════════════════════════════════════════════
class MultiLangAnalyzer:
    def __init__(self):
        self.name = "multilang_analyzer"

    def analyze(self, code: str, filename: str = "file.txt") -> Dict:
        lang = detect_language(filename)

        if lang == "python":
            result = check_python(code)
        elif lang in ("typescript", "javascript"):
            result = check_typescript(code, filename)
        elif lang == "json":
            result = check_json(code)
        elif lang == "yaml":
            result = check_yaml(code)
        elif lang == "markdown":
            result = check_markdown(code)
        else:
            result = {
                "language": lang,
                "issues": [],
                "verdict": "unknown",
            }

        result["filename"] = filename
        return result

    def analyze_file(self, path: str) -> Dict:
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            return self.analyze(content, path)
        except Exception as e:
            return {
                "filename": path,
                "language": "unknown",
                "issues": [{"type": "io", "line": 0,
                            "description": str(e)[:200],
                            "severity": "error"}],
                "verdict": "broken",
            }


multilang_analyzer = MultiLangAnalyzer()
