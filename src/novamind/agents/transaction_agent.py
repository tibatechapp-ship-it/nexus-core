"""Transaction Agent — Detects ACID and isolation issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.transaction_agent")


class TransactionAgent:

    def __init__(self):
        self.name = "transaction"
    """Detects transaction issues."""

    PATTERNS = {
        "missing_transaction": [
            (r'def.*:\s*\n(?:.*\n)*?\.save\(\)(?:.*\n)*?\.save\(\)', "Multiple saves without transaction"),
            (r'def.*:\s*\n(?:.*\n)*?\.create\(\)(?:.*\n)*?\.create\(\)', "Multiple creates — wrap in transaction"),
        ],
        "long_transaction": [
            (r'with\s+transaction\.atomic', "Transaction present — verify scope"),
            (r'BEGIN.*?(?:SELECT|UPDATE|INSERT)', "Long running transaction"),
        ],
        "isolation_level": [
            (r'isolation_level\s*=\s*["\']READ UNCOMMITTED["\']', "READ UNCOMMITTED — dirty reads"),
        ],
        "deadlock_risk": [
            (r'LOCK\s+IN\s+SHARE\s+MODE', "Row-level lock — deadlock risk"),
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
                            "severity": "high" if "deadlock" in category else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


transaction_agent = TransactionAgent()
__all__ = ["TransactionAgent", "transaction_agent"]
