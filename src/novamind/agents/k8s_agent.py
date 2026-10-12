"""Kubernetes Agent — Detects K8s manifest issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.k8s_agent")


class K8sAgent:

    def __init__(self):
        self.name = "k8s"
    """Detects Kubernetes manifest issues."""

    PATTERNS = {
        "security": [
            (r'privileged:\s*true', "Privileged container — security risk"),
            (r'runAsRoot:\s*true', "Running as root"),
            (r'hostNetwork:\s*true', "hostNetwork — security risk"),
            (r'hostPID:\s*true', "hostPID — security risk"),
        ],
        "resources": [
            (r'kind:\s*(?:Pod|Deployment)(?![\s\S]{0,500}resources:)', "Missing resources limits"),
            (r'cpu:\s*["\']?\d+["\']?$', "CPU without unit — use 'm' or 'm'"),
        ],
        "probes": [
            (r'kind:\s*(?:Pod|Deployment)(?![\s\S]{0,500}livenessProbe)', "Missing livenessProbe"),
            (r'kind:\s*(?:Pod|Deployment)(?![\s\S]{0,500}readinessProbe)', "Missing readinessProbe"),
        ],
        "image_policy": [
            (r'image:\s*.*:latest', "Using :latest — pin version"),
        ],
        "namespaces": [
            (r'^apiVersion(?![\s\S]{0,200}namespace:)', "Missing namespace"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        # Only for K8s YAML
        if filename and not any(x in filename.lower() for x in [".yaml", ".yml"]) and "k8s" not in filename.lower() and "kube" not in filename.lower():
            # Still check if content looks like K8s
            if "apiVersion" not in code or "kind:" not in code:
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


k8s_agent = K8sAgent()
__all__ = ["K8sAgent", "k8s_agent"]
