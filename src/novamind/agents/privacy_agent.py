"""Privacy Agent — Detects PII, GDPR, data leak issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.privacy_agent")


class PrivacyAgent:

    def __init__(self):
        self.name = "privacy"
    """Detects privacy and data protection issues."""

    PATTERNS = {
        "pii_logging": [
            (r'log(?:ger)?\.\w+\([^)]*(?:password|ssn|credit|email)', "PII in logs"),
            (r'print\s*\([^)]*(?:password|ssn|credit)', "PII printed"),
        ],
        "pii_storage": [
            (r'(?:ssn|credit_card|passport)\s*=\s*["\']', "PII stored in code"),
        ],
        "gdpr": [
            (r'DELETE\s+FROM\s+\w+\s*;', "Bulk DELETE — GDPR risk"),
            (r'TRUNCATE\s+TABLE', "TRUNCATE — GDPR risk"),
        ],
        "data_leak": [
            (r'response\.json\(\s*(?:user|person|account)\s*\)', "Full user data leak"),
            (r'\.values\s*\(\s*\)', "Consider .values_list with specific fields"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
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
                            "severity": "high" if "pii" in category else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


privacy_agent = PrivacyAgent()
__all__ = ["PrivacyAgent", "privacy_agent"]
