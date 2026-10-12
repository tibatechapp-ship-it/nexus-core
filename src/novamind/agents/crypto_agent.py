"""
Crypto Agent — Detects weak cryptography and key issues.
"""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.crypto_agent")


class CryptoAgent:

    def __init__(self):
        self.name = "crypto"
    """Detects cryptographic weaknesses."""

    PATTERNS = {
        "weak_hash": [
            (r'\bmd5\s*\(', "MD5 — use SHA-256+"),
            (r'\bsha1\s*\(', "SHA-1 — use SHA-256+"),
            (r'hashlib\.md5\b', "MD5 hashlib — replace"),
            (r'hashlib\.sha1\b', "SHA-1 hashlib — replace"),
        ],
        "weak_cipher": [
            (r'\bDES\b', "DES — use AES-256"),
            (r'\bRC4\b', "RC4 — use AES-256"),
            (r'\bBlowfish\b', "Blowfish — use AES-256"),
        ],
        "insecure_random": [
            (r'random\.random\s*\(', "random for crypto — use secrets"),
            (r'random\.randint\s*\(', "random for crypto — use secrets"),
            (r'Math\.random\s*\(.*(?:password|token|secret)', "Math.random for secrets"),
        ],
        "hardcoded_key": [
            (r'(?:secret|key|password)\s*=\s*["\'][A-Za-z0-9+/=]{16,}["\']', "Possible hardcoded key"),
            (r'-----BEGIN.*PRIVATE KEY-----', "Private key in code"),
        ],
        "weak_password_hash": [
            (r'sha256\s*\(\s*password', "SHA-256 for passwords — use bcrypt/argon2"),
            (r'md5\s*\(\s*password', "MD5 for passwords — critical"),
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
                            "severity": "high" if "password" in category else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        verdict = "issues" if issues else "ok"
        return {
            "ok": not issues,
            "verdict": verdict,
            "total": len(issues),
            "issues": issues,
        }


crypto_agent = CryptoAgent()
__all__ = ["CryptoAgent", "crypto_agent"]
