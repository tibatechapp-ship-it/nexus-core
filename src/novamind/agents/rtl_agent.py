"""RTL Agent — Detects Arabic RTL/LTR issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.rtl_agent")


class RTLAgent:

    def __init__(self):
        self.name = "rtl"
    """Detects RTL issues specific to Arabic."""

    ARABIC = r'[\u0600-\u06FF]'

    PATTERNS = {
        "missing_dir": [
            (rf'>\s*{ARABIC}', "Arabic content without dir='rtl'"),
            (rf'["\']({ARABIC}[^"\']*)["\'](?!.*dir)', "Arabic string — verify dir"),
        ],
        "mixed_direction": [
            (rf'{ARABIC}[a-zA-Z]', "Mixed Arabic+Latin — consider isolation"),
            (rf'[a-zA-Z]{ARABIC}', "Mixed Latin+Arabic — consider isolation"),
        ],
        "css_logical": [
            (r'margin-left\s*:', "Use margin-inline-start (RTL-friendly)"),
            (r'margin-right\s*:', "Use margin-inline-end"),
            (r'padding-left\s*:', "Use padding-inline-start"),
            (r'padding-right\s*:', "Use padding-inline-end"),
            (r'text-align:\s*left', "Use text-align: start"),
            (r'text-align:\s*right', "Use text-align: end"),
        ],
        "flexbox_rtl": [
            (r'flex-direction:\s*row(?![^}]*rtl)', "Consider direction in flex containers"),
        ],
        "numbers": [
            (rf'{ARABIC}\d', "Consider Arabic-Indic numerals or ensure alignment"),
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
                    regex = re.compile(pattern)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith(("//", "/*", "*", "#")):
                        continue
                    if regex.search(line):
                        # Skip if dir already set
                        if category == "missing_dir" and "dir=" in line:
                            continue
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "medium",
                            "description": desc,
                            "snippet": stripped[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


rtl_agent = RTLAgent()
__all__ = ["RTLAgent", "rtl_agent"]
