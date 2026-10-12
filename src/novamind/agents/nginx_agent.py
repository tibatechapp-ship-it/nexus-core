"""Nginx Agent — Detects Nginx config issues."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.nginx_agent")


class NginxAgent:

    def __init__(self):
        self.name = "nginx"
    """Detects Nginx configuration issues."""

    PATTERNS = {
        "security_headers": [
            (r'add_header\s+X-Frame-Options', "Consider X-Frame-Options header"),
            (r'add_header\s+X-Content-Type-Options', "Consider X-Content-Type-Options"),
            (r'add_header\s+Strict-Transport-Security', "Consider HSTS"),
        ],
        "ssl": [
            (r'ssl_protocols\s+.*(?:TLSv1\b|TLSv1\.1)', "Old TLS versions — use 1.2+"),
            (r'ssl_ciphers\s+HIGH:!aNULL(?!:!MD5:!RC4)', "Add :!MD5:!RC4 to ciphers"),
        ],
        "performance": [
            (r'gzip\s+off', "Gzip disabled — consider enabling"),
            (r'client_max_body_size\s+\d+G', "Very large body size"),
        ],
        "proxy": [
            (r'proxy_pass\s+http://', "Consider HTTPS upstream"),
            (r'proxy_set_header\s+Host\s+\$host(?!:$)', "Check Host header"),
        ],
        "rate_limit": [
            (r'limit_req_zone', "Rate limit configured (good)"),
            (r'limit_conn', "Connection limit (good)"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        # Only nginx files
        if filename and "nginx" not in filename.lower() and not filename.endswith(".conf"):
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
                        # Only flag missing (add_header pattern is "consider")
                        if "Consider" in desc and regex.search(line):
                            continue
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "high" if "ssl" in category else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


nginx_agent = NginxAgent()
__all__ = ["NginxAgent", "nginx_agent"]
