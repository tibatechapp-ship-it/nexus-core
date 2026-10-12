"""NoSQL Agent — Detects MongoDB, Redis, Elasticsearch issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.nosql_agent")


class NoSQLAgent:

    def __init__(self):
        self.name = "nosql"
    """Detects NoSQL anti-patterns."""

    PATTERNS = {
        "mongodb": [
            (r'\.find\s*\(\s*\{\s*\}\s*\)', "Empty find() — fetch everything"),
            (r'\.find\s*\(\s*\{[^}]*\$where', "$where — injection risk"),
            (r'\.updateOne\s*\([^)]*(?:\$set|\.\.\.)', "Update with spread — check"),
        ],
        "redis": [
            (r'\.keys\s*\(', "KEYS command — use SCAN in production"),
            (r'\.flushall\s*\(', "FLUSHALL — dangerous"),
            (r'\.flushdb\s*\(', "FLUSHDB — dangerous"),
        ],
        "elasticsearch": [
            (r'\.search\s*\([^)]*match_all', "match_all — heavy query"),
            (r'size\s*:\s*\d{4,}', "Very large size — paginate instead"),
        ],
        "cassandra": [
            (r'SELECT\s+\*\s+FROM', "SELECT * in Cassandra — inefficient"),
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
                    regex = re.compile(pattern, re.IGNORECASE)
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


nosql_agent = NoSQLAgent()
__all__ = ["NoSQLAgent", "nosql_agent"]
