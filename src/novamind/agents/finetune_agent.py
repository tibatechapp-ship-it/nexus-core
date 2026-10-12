"""Fine-tune Agent — Detects fine-tuning data issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.finetune_agent")


class FinetuneAgent:

    def __init__(self):
        self.name = "finetune"
    """Detects fine-tuning issues."""

    PATTERNS = {
        "data_quality": [
            (r'"messages"\s*:\s*\[\s*\]', "Empty messages array"),
            (r'"role"\s*:\s*"(?!system|user|assistant)', "Invalid role"),
            (r'"content"\s*:\s*""', "Empty content"),
        ],
        "format": [
            (r'\.jsonl?\b', "Verify JSONL format"),
            (r'json\.load\s*\([^)]*\)\s*#.*jsonl', "Use jsonl parsing"),
        ],
        "balance": [
            (r'"role"\s*:\s*"assistant"', "Check balance of roles"),
        ],
        "size": [
            (r'<\\s*100\\s*\\b.*train', "Very small training set"),
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
                            "severity": "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


finetune_agent = FinetuneAgent()
__all__ = ["FinetuneAgent", "finetune_agent"]
