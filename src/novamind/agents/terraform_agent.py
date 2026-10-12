"""Terraform Agent — Detects IaC issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.terraform_agent")


class TerraformAgent:

    def __init__(self):
        self.name = "terraform"
    """Detects Terraform issues."""

    PATTERNS = {
        "security": [
            (r'acl\s*=\s*["\']public-read["\']', "Public S3 ACL — security risk"),
            (r'cidr_blocks\s*=\s*\[["\']0\.0\.0\.0/0["\']', "Open to 0.0.0.0/0"),
            (r'encryption\s*=\s*false', "Encryption disabled"),
            (r'publicly_accessible\s*=\s*true', "Publicly accessible"),
        ],
        "best_practices": [
            (r'resource\s+"aws_\w+"(?![\s\S]{0,200}tags\s*=)', "Resource without tags"),
            (r'provider\s+"aws"(?![\s\S]{0,200}region)', "Provider without region"),
        ],
        "state": [
            (r'backend\s+"local"', "Local backend — use remote for teams"),
        ],
        "variables": [
            (r'variable\s+"\w+"\s*\{[^}]*default\s*=', "Variable with default — verify"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        # Only .tf files
        if filename and not filename.endswith(".tf"):
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0, "skipped": True}

        issues = []
        lines = code.split("\n")

        for category, patterns in self.PATTERNS.items():
            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith("#"):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "high" if category == "security" else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


terraform_agent = TerraformAgent()
__all__ = ["TerraformAgent", "terraform_agent"]
