"""Evaluation Agent — Detects LLM evaluation issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.evaluation_agent")


class EvaluationAgent:

    def __init__(self):
        self.name = "evaluation"
    """Detects LLM evaluation issues."""

    PATTERNS = {
        "metrics": [
            (r'accuracy\s*=\s*(?:true|false|1|0)\s*$', "Binary accuracy — use F1/confusion"),
            (r'\.score\s*\(\s*\)', "Generic score — specify metric"),
        ],
        "benchmark": [
            (r'benchmark\s*=\s*\[\s*["\']\w+["\']\s*\]', "Single benchmark — use multiple"),
            (r'MMLU.*HumanEval', "Mixed benchmarks — verify compatibility"),
        ],
        "bias": [
            (r'gender\s*=', "Check for bias in gender"),
            (r'race\s*=', "Check for bias in race"),
        ],
        "safety": [
            (r'content_filter\s*=\s*False', "Content filter disabled"),
            (r'nsfw_check\s*=\s*False', "NSFW check disabled"),
        ],
        "cost": [
            (r'tokens?\s*=\s*\d{6,}', "Very high token usage"),
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


evaluation_agent = EvaluationAgent()
__all__ = ["EvaluationAgent", "evaluation_agent"]
