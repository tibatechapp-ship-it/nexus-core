"""Monitoring Agent — Detects observability issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.monitoring_agent")


class MonitoringAgent:

    def __init__(self):
        self.name = "monitoring"
    """Detects monitoring/observability issues."""

    PATTERNS = {
        "logging": [
            (r'print\s*\(', "Use logger instead of print"),
            (r'console\.log\s*\(', "console.log in production"),
            (r'log\.(?:error|warn|info)\s*\([^)]*(?:password|token|secret)', "Secrets in logs"),
        ],
        "error_handling": [
            (r'except\s*:\s*pass', "Bare except — log instead"),
            (r'catch\s*\(\s*\)\s*\{\s*\}', "Empty catch — log instead"),
        ],
        "metrics": [
            (r'@app\.route(?![\s\S]{0,200}metrics)', "No metrics on route"),
        ],
        "health": [
            (r'health_check\s*=', "Health check configured (good)"),
        ],
        "traces": [
            (r'opentelemetry', "OpenTelemetry (good)"),
            (r'jaeger', "Jaeger tracing (good)"),
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
                            "severity": "medium" if "log" in category.lower() else "low",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


monitoring_agent = MonitoringAgent()
__all__ = ["MonitoringAgent", "monitoring_agent"]
