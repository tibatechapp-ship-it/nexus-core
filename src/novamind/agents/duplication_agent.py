"""Duplication Agent — Detects code duplication (DRY violations)."""
import logging
from typing import Dict, List
from collections import Counter

logger = logging.getLogger("agents.duplication_agent")


class DuplicationAgent:

    def __init__(self):
        self.name = "duplication"
    """Detects duplicated code."""

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        # Track duplicates (normalized)
        normalized = []
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if not s or s.startswith(("#", "//", '"""', "'''")):
                continue
            if len(s) < 15:  # skip short lines
                continue
            normalized.append((i, s))

        counter = Counter([s for _, s in normalized])
        seen = {}

        for i, s in normalized:
            if counter[s] >= 3:
                if s not in seen:
                    seen[s] = {
                        "line": i,
                        "category": "duplication",
                        "severity": "medium",
                        "description": f"Line repeated {counter[s]} times: {s[:50]}",
                        "count": counter[s],
                    }
                    issues.append(seen[s])

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


duplication_agent = DuplicationAgent()
__all__ = ["DuplicationAgent", "duplication_agent"]
