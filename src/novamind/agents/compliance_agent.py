"""Compliance Agent — Detects SOC2, ISO 27001, HIPAA, PCI issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.compliance_agent")


class ComplianceAgent:

    def __init__(self):
        self.name = "compliance"
    """Detects compliance issues."""

    PATTERNS = {
        "soc2": [
            (r'DEBUG\s*=\s*True', "DEBUG=True in production — SOC2 risk"),
            (r'ALLOWED_HOSTS\s*=\s*\[\s*["\']\*["\']', "ALLOWED_HOSTS=* — SOC2"),
            (r'CORS_ORIGIN_ALLOW_ALL\s*=\s*True', "CORS all — SOC2"),
        ],
        "pci": [
            (r'card_number\s*[:=]', "Card number — PCI risk"),
            (r'cvv\s*[:=]', "CVV — PCI risk"),
        ],
        "hipaa": [
            (r'(?:patient|diagnosis|medication)_\w+\s*=', "PHI data — HIPAA"),
        ],
        "audit": [
            (r'@app\.route.*(?:delete|drop)', "No audit for delete/drop"),
            (r'sudo\s+rm\s+-rf', "Destructive command"),
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


compliance_agent = ComplianceAgent()
__all__ = ["ComplianceAgent", "compliance_agent"]
