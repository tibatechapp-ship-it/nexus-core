"""
Injection Agent — Detects SQL, NoSQL, Command, LDAP injection.
"""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.injection_agent")


class InjectionAgent:

    def __init__(self):
        self.name = "injection"
    """Detects various injection vulnerabilities."""

    PATTERNS = {
        "sql_injection": [
            (r'execute\s*\(\s*f["\']', "SQL via f-string"),
            (r'execute\s*\(\s*["\'].*%s.*["\']\s*%', "SQL via %"),
            (r'execute\s*\(\s*["\'].*\+', "SQL concatenation"),
            (r'\.raw\s*\(', "Django raw SQL"),
            (r'query\s*\(\s*`[^`]*\$\{', "SQL template literal"),
        ],
        "nosql_injection": [
            (r'\.find\s*\(\s*\{[^}]*\$where', "MongoDB $where — avoid"),
            (r'\.find\s*\(\s*req\.', "MongoDB from user input"),
        ],
        "command_injection": [
            (r'os\.system\s*\(', "os.system — use subprocess list"),
            (r'subprocess\.[a-z]+\([^)]*shell\s*=\s*True', "shell=True"),
            (r'os\.popen\s*\(', "os.popen"),
            (r'child_process\.exec\s*\(', "exec"),
            (r'`[^`]*\$\{[^}]*req\.', "Template literal with user input"),
        ],
        "ldap_injection": [
            (r'ldap.*search.*\bf["\']', "LDAP f-string"),
        ],
        "xpath_injection": [
            (r'xpath\s*\([^)]*\+', "XPath concatenation"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code or not code.strip():
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
                            "severity": "critical" if "sql" in category or "command" in category else "high",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        verdict = "broken" if any(i["severity"] == "critical" for i in issues) else ("issues" if issues else "ok")
        return {
            "ok": not issues,
            "verdict": verdict,
            "total": len(issues),
            "issues": issues,
        }


injection_agent = InjectionAgent()
__all__ = ["InjectionAgent", "injection_agent"]
