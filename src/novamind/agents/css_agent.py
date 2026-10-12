"""CSS Agent — Detects CSS/Tailwind issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.css_agent")


class CSSAgent:

    def __init__(self):
        self.name = "css"
    """Detects CSS issues."""

    PATTERNS = {
        "specificity": [
            (r'!important', "!important — high specificity"),
        ],
        "performance": [
            (r'\*\s*\{', "Universal selector — perf issue"),
            (r'@import\s+url', "@import — blocking, use <link>"),
        ],
        "responsive": [
            (r'width:\s*\d{4,}px', "Fixed large width — use % or vw"),
            (r'(?:margin|padding):\s*\d{3,}px', "Very large margin/padding"),
        ],
        "accessibility": [
            (r'outline:\s*none', "Removes focus outline — a11y issue"),
            (r'outline:\s*0', "Removes focus outline — a11y issue"),
            (r'font-size:\s*\d+px', "Consider rem for font-size"),
        ],
        "tailwind": [
            (r'className="[^"]*m-\d{3,}', "Very large margin (Tailwind)"),
            (r'className="[^"]*w-\[\d{4,}px\]', "Arbitrary fixed width"),
        ],
        "modern": [
            (r'float:\s*(?:left|right)', "Float — consider flexbox/grid"),
            (r'display:\s*table', "Display:table — consider grid"),
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
                            "severity": "high" if "accessibility" in category else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


css_agent = CSSAgent()
__all__ = ["CSSAgent", "css_agent"]
