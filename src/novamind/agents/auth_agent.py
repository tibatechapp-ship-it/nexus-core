"""
Auth Agent — Detects authentication and authorization issues.
"""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.auth_agent")


class AuthAgent:

    def __init__(self):
        self.name = "auth"
    """Detects authentication/authorization issues."""

    PATTERNS = {
        "weak_auth": [
            (r'password\s*==\s*["\']\w{1,6}["\']', "Short hardcoded password"),
            (r'if\s+\w+\s*==\s*["\']admin["\']', "Hardcoded admin check"),
            (r'if\s+\w+\s*==\s*["\']root["\']', "Hardcoded root check"),
        ],
        "jwt_issues": [
            (r'jwt\.decode\s*\([^)]*verify\s*=\s*False', "JWT verify=False"),
            (r'algorithm\s*=\s*["\']none["\']', "JWT alg=none — critical"),
            (r'jwt\.decode\s*\([^,)]+\)', "JWT decode without verify"),
        ],
        "session_issues": [
            (r'SESSION_COOKIE_SECURE\s*=\s*False', "Session cookie not secure"),
            (r'SESSION_COOKIE_HTTPONLY\s*=\s*False', "Session cookie not httponly"),
            (r'SESSION_EXPIRE_AT_BROWSER_CLOSE\s*=\s*True', "Session too permissive"),
        ],
        "oauth_issues": [
            (r'oauth.*http://', "OAuth over HTTP"),
            (r'redirect_uri\s*=\s*["\']http://', "OAuth http redirect"),
        ],
        "authorization": [
            (r'@login_required', "Consider additional authz checks"),
            (r'permission_classes\s*=\s*\[\s*\]', "Empty permission classes"),
            (r'AllowAny', "AllowAny permission"),
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
                            "severity": "critical" if "jwt" in category else "high",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "broken" if any(i["severity"] == "critical" for i in issues) else ("issues" if issues else "ok"),
            "total": len(issues),
            "issues": issues,
        }


auth_agent = AuthAgent()
__all__ = ["AuthAgent", "auth_agent"]
