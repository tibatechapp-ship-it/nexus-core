"""A11y Agent — Detects accessibility issues (WCAG)."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.a11y_agent")


class A11yAgent:

    def __init__(self):
        self.name = "a11y"
    """Detects accessibility issues."""

    PATTERNS = {
        "images": [
            (r'<img(?![^>]*\balt\s*=)[^>]*>', "img without alt attribute"),
            (r'alt\s*=\s*["\']image["\']', "Generic alt — use descriptive"),
        ],
        "buttons": [
            (r'<div[^>]*onClick[^>]*>', "div with onClick — use <button>"),
            (r'<button(?![^>]*aria-)[^>]*>[^<]*<i[^>]*>', "Icon-only button — add aria-label"),
        ],
        "forms": [
            (r'<input(?![^>]*(?:aria-label|id))[^>]*>', "Input without label"),
            (r'<label(?![^>]*for=)', "Label without 'for' attribute"),
        ],
        "aria": [
            (r'aria-label\s*=\s*["\']\s*["\']', "Empty aria-label"),
            (r'role\s*=\s*["\']\s*["\']', "Empty role"),
        ],
        "contrast": [
            (r'color:\s*#(?:[0-9a-f]{6})', "Verify color contrast (WCAG AA)"),
        ],
        "landmarks": [
            (r'<html(?![^>]*lang)', "HTML without lang"),
        ],
        "rtl": [
            (r'dir\s*=\s*["\']ltr["\'][^>]*>\s*[\u0600-\u06FF]', "Arabic content with dir=ltr"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        for category, patterns in self.PATTERNS.items():
            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.MULTILINE)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith(("//", "/*", "*")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "high" if category in ("images", "forms") else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


a11y_agent = A11yAgent()
__all__ = ["A11yAgent", "a11y_agent"]
