"""ORM Agent — Detects SQLAlchemy, Django ORM, Prisma issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.orm_agent")


class ORMAgent:

    def __init__(self):
        self.name = "orm"
    """Detects ORM issues."""

    PATTERNS = {
        "sqlalchemy": [
            (r'session\.query\([^)]+\)\.all\(\)', ".all() without limit"),
            (r'\.lazy\s*=\s*["\']select["\']', "select lazy loading — N+1 risk"),
            (r'\.execute\s*\(f["\']', "SQL execution with f-string"),
        ],
        "django": [
            (r'\.objects\.all\s*\(\s*\)', ".all() — consider pagination"),
            (r'\.values\s*\(\s*\)', ".values() — fetch all fields"),
            (r'\.raw\s*\(', "Raw SQL — injection risk"),
        ],
        "prisma": [
            (r'prisma\.\w+\.findMany\s*\(\s*\)', "findMany without where"),
            (r'include:\s*\{[^}]*\{[^}]*\{', "Deep include — heavy query"),
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


orm_agent = ORMAgent()
__all__ = ["ORMAgent", "orm_agent"]
