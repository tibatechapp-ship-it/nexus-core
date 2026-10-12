"""DB Migration Agent — Detects database migration issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.db_migration_agent")


class DBMigrationAgent:

    def __init__(self):
        self.name = "db_migration"
    """Detects migration issues."""

    PATTERNS = {
        "dangerous_drop": [
            (r'drop_table\s*\(', "DROP TABLE — destructive"),
            (r'drop_column\s*\(', "DROP COLUMN — destructive"),
            (r'delete\s*\(', "DELETE in migration — check"),
        ],
        "missing_default": [
            (r'add_column\s*\([^,]+,\s*[^,)]+\)(?!\s*,[^)]*default)', "NOT NULL column without default"),
        ],
        "long_operations": [
            (r'alter_column.*nullable\s*=\s*False', "ALTER nullable=False — lock risk"),
            (r'create_index.*\bunique\s*=\s*True', "Unique index — lock on big tables"),
        ],
        "data_loss": [
            (r'alter_column.*type_', "Column type change — data loss risk"),
            (r'drop_constraint', "Dropping constraint — verify"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        # Only check migration files
        if filename and "migration" not in filename.lower() and "alembic" not in filename.lower():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0, "skipped": True}

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
                            "severity": "high",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


db_migration_agent = DBMigrationAgent()
__all__ = ["DBMigrationAgent", "db_migration_agent"]
