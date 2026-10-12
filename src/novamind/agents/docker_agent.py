"""Docker Agent — Detects Dockerfile issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.docker_agent")


class DockerAgent:

    def __init__(self):
        self.name = "docker"
    """Detects Dockerfile issues."""

    PATTERNS = {
        "security": [
            (r'USER\s+root', "Running as root — use non-root user"),
            (r'FROM\s+.*:latest', "Using :latest — pin version"),
            (r'ADD\s+http', "ADD with URL — use COPY + curl"),
            (r'--no-install-recommends', "Consider --no-install-recommends (exists — ok)"),
        ],
        "size": [
            (r'RUN\s+apt-get\s+update(?!\s*&&\s*apt-get\s+install)', "Separate apt-get update"),
            (r'COPY\s+\.\s+\.', "COPY . . — use .dockerignore"),
            (r'RUN\s+pip\s+install\s+--no-cache-dir(?!\s+-r)', "Consider --no-cache-dir"),
        ],
        "build_speed": [
            (r'COPY\s+\.\s+\..*RUN\s+(?:npm|pip)\s+install', "COPY before deps — cache issue"),
        ],
        "missing": [
            (r'^FROM\s+\w+(?!.*AS)', "Consider multi-stage build"),
        ],
        "healthcheck": [
            (r'^FROM(?![\s\S]*HEALTHCHECK)', "No HEALTHCHECK"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        # Only for Dockerfile
        if filename and not any(x in filename.lower() for x in ["dockerfile", "docker-compose"]):
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


docker_agent = DockerAgent()
__all__ = ["DockerAgent", "docker_agent"]
