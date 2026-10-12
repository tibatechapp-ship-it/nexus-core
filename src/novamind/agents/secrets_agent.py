"""Secrets Agent — Detects hardcoded secrets and API keys."""
import logging
import re
from typing import Dict, List
import os

logger = logging.getLogger("agents.secrets_agent")


class SecretsAgent:

    def __init__(self):
        self.name = "secrets"
    """Detects hardcoded secrets."""

    PATTERNS = {
        "aws_key": (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
        "aws_secret": (r'aws.{0,20}?["\'][0-9a-zA-Z/+]{40}["\']', "AWS Secret"),
        "github_token": (r'ghp_[A-Za-z0-9]{36}', "GitHub Token"),
        "github_pat": (r'github_pat_[A-Za-z0-9_]{20,}', "GitHub PAT"),
        "google_api": (r'AIza[A-Za-z0-9_-]{35}', "Google API Key"),
        "openai_key": (r'sk-[A-Za-z0-9]{48}', "OpenAI Key"),
        "openai_proj": (r'sk-proj-[A-Za-z0-9_-]{40,}', "OpenAI Project Key"),
        "groq_key": (r'gsk_[A-Za-z0-9]{50,}', "Groq Key"),
        "stripe_key": (r'sk_live_[A-Za-z0-9]{24,}', "Stripe Live Key"),
        "slack_token": (r'xox[baprs]-[A-Za-z0-9-]+', "Slack Token"),
        "telegram_bot": (r'\d{8,10}:[A-Za-z0-9_-]{35}', "Telegram Bot Token"),
        "private_key": (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', "Private Key"),
        "jwt": (r'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}', "JWT"),
        "generic_password": (r'(?:password|passwd|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']', "Hardcoded password"),
        "generic_secret": (r'(?:secret|secret_key|api_key|apikey|access_token|auth_token|private_key|encryption_key)\s*[:=]\s*["\'][^"\']{8,}["\']', "Hardcoded secret/key"),
        "generic_token": (r'(?:token|bearer)\s*[:=]\s*["\'][A-Za-z0-9_\-\.]{16,}["\']', "Hardcoded token"),
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        for name, (pattern, desc) in self.PATTERNS.items():
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            for i, line in enumerate(lines, 1):
                if line.strip().startswith(("#", "//")):
                    continue
                if any(x in line for x in ["os.environ", "getenv", "process.env",
                                             "your_", "<", "XXX", "example"]):
                    continue
                m = regex.search(line)
                if m:
                    redacted = line[:m.start()] + "***REDACTED***" + line[m.end():]
                    issues.append({
                        "line": i,
                        "category": name,
                        "severity": "critical",
                        "description": f"Hardcoded: {desc}",
                        "snippet": redacted.strip()[:100],
                    })

        return {
            "ok": not issues,
            "verdict": "broken" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


secrets_agent = SecretsAgent()
__all__ = ["SecretsAgent", "secrets_agent"]
