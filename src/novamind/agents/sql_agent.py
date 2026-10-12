"""SQL Agent — Detects SQL anti-patterns and optimizations."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.sql_agent")


class SQLAgent:

    def __init__(self):
        self.name = "sql"
    """Detects SQL issues."""

    PATTERNS = {
        "select_star": [
            (r'SELECT\s+\*\s+FROM', "Avoid SELECT * — select specific columns"),
        ],
        "missing_where": [
            (r'\bDELETE\s+FROM\s+\w+\s*;', "DELETE without WHERE — dangerous"),
            (r'\bUPDATE\s+\w+\s+SET\s+[^;]*;', "UPDATE without WHERE — check"),
        ],
        "missing_index": [
            (r'WHERE\s+\w+\s*=\s*\?', "Consider index on WHERE column"),
            (r'ORDER\s+BY\s+\w+', "Consider index on ORDER BY"),
        ],
        "n_plus_one": [
            (r'for.*:\s*\n\s+.*\.(?:query|filter|get)\s*\(', "Possible N+1 query"),
        ],
        "join_issues": [
            (r'CROSS\s+JOIN', "CROSS JOIN — verify intentional"),
            (r'LEFT\s+JOIN.*LEFT\s+JOIN.*LEFT\s+JOIN.*LEFT\s+JOIN', "Many joins — consider denormalization"),
        ],
        "subquery": [
            (r'SELECT.*\(SELECT.*FROM', "Subquery — consider JOIN"),
        ],
        "null_comparison": [
            (r'=\s*NULL', "Use IS NULL not = NULL"),
            (r'!=\s*NULL', "Use IS NOT NULL not != NULL"),
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
                    if line.strip().startswith(("#", "--")):
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


sql_agent = SQLAgent()
__all__ = ["SQLAgent", "sql_agent"]
