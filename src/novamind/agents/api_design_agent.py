"""API Design Agent — Detects REST/GraphQL design issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.api_design_agent")


class APIDesignAgent:

    def __init__(self):
        self.name = "api_design"
    """Detects API design issues."""

    PATTERNS = {
        "rest_naming": [
            (r'@app\.route\s*\(\s*["\']/[a-z_]+/(?:get|create|update|delete)', "REST: use HTTP methods"),
            (r'/get[A-Z]', "REST: don't use 'get' prefix"),
            (r'\.(?:get|post)\s*\(\s*["\'][A-Z]', "Endpoints should be lowercase"),
        ],
        "status_codes": [
            (r'return\s+.*,\s*200.*(?:create|delete)', "Use 201 for create, 204 for delete"),
            (r'return\s+.*,\s*200.*error', "Return error status codes"),
        ],
        "pagination": [
            (r'\.all\s*\(\s*\)', "Consider pagination for .all()"),
            (r'find\s*\(\s*\{\s*\}\s*\)', "Empty find() — add pagination"),
        ],
        "versioning": [
            (r'@app\.route\s*\(\s*["\']/api/(?!v\d)', "Add API version (/api/v1/)"),
        ],
        "graphql": [
            (r'graphql.*select\s*\*', "GraphQL: avoid select *"),
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
                            "severity": "info",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


api_design_agent = APIDesignAgent()
__all__ = ["APIDesignAgent", "api_design_agent"]
