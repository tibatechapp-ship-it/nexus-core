"""
XSS Agent — Detects XSS, CSRF, clickjacking vulnerabilities.
"""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.xss_agent")


class XSSAgent:

    def __init__(self):
        self.name = "xss"
    """Detects XSS, CSRF, and clickjacking issues."""

    PATTERNS = {
        "xss": [
            (r'dangerouslySetInnerHTML', "React dangerouslySetInnerHTML"),
            (r'\.innerHTML\s*=', "Direct innerHTML — use textContent"),
            (r'document\.write\s*\(', "document.write"),
            (r'\.html\s*\(\s*[^)]*\$', "jQuery .html() with user data"),
            (r'mark_safe\s*\(', "Django mark_safe"),
            (r'\|\s*safe\b', "Django |safe filter"),
            (r'render_template_string\s*\(', "Flask render_template_string"),
        ],
        "csrf": [
            (r'@app\.route.*methods.*POST(?![^)]*csrf)', "Flask POST without CSRF"),
            (r'@csrf_exempt', "Django csrf_exempt"),
            (r'skip_csrf', "CSRF skipped"),
        ],
        "clickjacking": [
            (r'X-Frame-Options', "Consider X-Frame-Options check"),
        ],
        "unsafe_eval": [
            (r'\beval\s*\(', "eval() — XSS risk"),
            (r'new Function\s*\(', "new Function() — XSS risk"),
            (r'setTimeout\s*\(\s*["\']', "setTimeout with string — XSS"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code or not code.strip():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        for category, patterns in self.PATTERNS.items():
            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith(("#", "//")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "high" if category == "xss" else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


xss_agent = XSSAgent()
__all__ = ["XSSAgent", "xss_agent"]
