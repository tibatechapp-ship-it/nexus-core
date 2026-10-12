"""Indexing Agent — Detects missing indexes."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.indexing_agent")


class IndexingAgent:

    def __init__(self):
        self.name = "indexing"
    """Detects missing/poor indexes."""

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        # Check for WHERE without index
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Query patterns
            if re.search(r'WHERE\s+(\w+)\s*=', line, re.IGNORECASE):
                col = re.search(r'WHERE\s+(\w+)\s*=', line, re.IGNORECASE).group(1)
                # Check if indexed
                indexed = False
                for j, l in enumerate(lines):
                    if col in l and "index" in l.lower():
                        indexed = True
                        break
                if not indexed:
                    issues.append({
                        "line": i,
                        "category": "missing_index",
                        "severity": "info",
                        "description": f"WHERE on '{col}' — verify index exists",
                    })

            # ORM patterns
            if re.search(r'\.filter\s*\(\s*(\w+)\s*=', line):
                col = re.search(r'\.filter\s*\(\s*(\w+)\s*=', line).group(1)
                issues.append({
                    "line": i,
                    "category": "orm_index",
                    "severity": "info",
                    "description": f"Consider db_index=True for '{col}'",
                })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


indexing_agent = IndexingAgent()
__all__ = ["IndexingAgent", "indexing_agent"]
