"""Dependency Agent — Detects vulnerable dependencies."""
import logging
import json
import re
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("agents.dependency_agent")

KNOWN_VULNERABLE = {
    "django<4.0": "Django < 4.0 has multiple CVEs",
    "flask<2.3": "Flask < 2.3 security issues",
    "requests<2.31": "requests < 2.31 CVE-2023-32681",
    "urllib3<2.0": "urllib3 < 2.0 CVE-2023-43804",
    "pyyaml<6.0": "PyYAML < 6.0 CVE-2020-14343",
    "jinja2<3.1": "Jinja2 < 3.1 CVE-2024-22195",
    "setuptools<83": "setuptools < 83 PYSEC-2026-3447",
    "cryptography<42": "cryptography < 42 CVE issues",
    "lodash<4.17.21": "lodash < 4.17.21 prototype pollution",
    "axios<1.6": "axios < 1.6 SSRF",
}


class DependencyAgent:

    def __init__(self):
        self.name = "dependency"
    """Detects vulnerable dependencies."""

    def analyze(self, code: str, filename: str = "") -> Dict:
        issues = []

        # Only scan dependency files
        dep_files = {"requirements.txt", "requirements-ci.txt",
                     "package.json", "pyproject.toml", "Pipfile"}

        if filename and Path(filename).name not in dep_files:
            # Still scan content for pip install
            for i, line in enumerate(code.split("\n"), 1):
                match = re.search(r'pip\s+install\s+([a-zA-Z0-9_-]+)', line)
                if match:
                    pkg = match.group(1).lower()
                    issues.append({
                        "line": i,
                        "category": "runtime_install",
                        "severity": "low",
                        "description": f"Runtime pip install: {pkg}",
                    })
            return {"ok": not issues, "verdict": "issues" if issues else "ok",
                    "total": len(issues), "issues": issues}

        # Parse dependency file
        for i, line in enumerate(code.split("\n"), 1):
            line = line.strip()
            if not line or line.startswith(("#", "//")):
                continue

            for vuln_pattern, desc in KNOWN_VULNERABLE.items():
                pkg, version = vuln_pattern.split("<")
                if pkg in line.lower() and version in line:
                    issues.append({
                        "line": i,
                        "category": "known_cve",
                        "severity": "high",
                        "description": desc,
                        "snippet": line[:100],
                    })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


dependency_agent = DependencyAgent()
__all__ = ["DependencyAgent", "dependency_agent"]
