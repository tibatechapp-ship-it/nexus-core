"""CI/CD Agent — Detects CI/CD pipeline issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.cicd_agent")


class CICDAgent:

    def __init__(self):
        self.name = "cicd"
    """Detects CI/CD issues."""

    PATTERNS = {
        "github_actions": [
            (r'uses:\s*actions/checkout@v[12]', "Update checkout to v4+"),
            (r'uses:\s*actions/setup-python@v[12]', "Update setup-python to v5+"),
            (r'runs-on:\s*ubuntu-18', "Ubuntu 18 deprecated"),
            (r'\bsecrets\.\w+\s*\)\s*cache', "Caching with secrets — risky"),
        ],
        "gitlab_ci": [
            (r'image:\s*.*:latest', "Pin CI image version"),
            (r'only:\s*-\s*master', "Update to 'main' or use rules:"),
        ],
        "generic": [
            (r'\bsudo\s', "Avoid sudo in CI"),
            (r'--force', "Force flag — verify"),
            (r'DISABLE_SSL', "SSL disabled — security issue"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        # CI files
        if filename and not any(x in filename.lower() for x in [".yml", ".yaml", "ci", "cd", "pipeline", "workflow"]):
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


cicd_agent = CICDAgent()
__all__ = ["CICDAgent", "cicd_agent"]
