"""Prompt Agent — Detects prompt engineering issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.prompt_agent")


class PromptAgent:

    def __init__(self):
        self.name = "prompt"
    """Detects prompt issues in code."""

    PATTERNS = {
        "quality": [
            (r'system\s*=\s*["\']\s*["\']', "Empty system prompt"),
            (r'prompt\s*=\s*["\']\s*["\']', "Empty user prompt"),
            (r'max_tokens\s*=\s*(?:0|1|2|3|4|5)\b', "Very low max_tokens"),
        ],
        "safety": [
            (r'ignore\s+(?:all\s+)?(?:previous|prior)', "Prompt injection pattern"),
            (r'you\s+are\s+now\s+', "Role hijacking pattern"),
            (r'(?:jailbreak|DAN\s+mode)', "Jailbreak pattern"),
        ],
        "structure": [
            (r'prompt\s*=\s*f["\'].*\n.*\{.*\}.*\n.*', "Multi-line f-string prompt — consider template"),
            (r'\.format\s*\([^)]*password', "Secrets in prompt"),
        ],
        "temperature": [
            (r'temperature\s*=\s*(?:[2-9]|1\.[5-9])', "Very high temperature — verify"),
        ],
        "token_limits": [
            (r'input\s*\+\s*output\s*>\s*\d{4,}', "Token overflow risk"),
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
                    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith(("#", "//")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "high" if category == "safety" else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


prompt_agent = PromptAgent()
__all__ = ["PromptAgent", "prompt_agent"]
