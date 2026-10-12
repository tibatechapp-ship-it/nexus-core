"""
SecretScanner — كاشف المفاتيح المسرّبة
========================================
يعمل محلياً بدون LLM.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

logger = logging.getLogger("nova.agents.secret_scanner")


@dataclass
class SecretPattern:
    name: str
    pattern: str
    severity: str
    description: str

    def compiled(self):
        return re.compile(self.pattern, re.IGNORECASE)


DEFAULT_PATTERNS = [
    SecretPattern("openai_key", r"sk-[a-zA-Z0-9]{20,}", "critical", "OpenAI API key"),
    SecretPattern("google_api_key", r"AIza[a-zA-Z0-9_\-]{30,}", "critical", "Google/Gemini API key"),
    SecretPattern("groq_key", r"gsk_[a-zA-Z0-9]{40,}", "critical", "Groq API key"),
    SecretPattern("anthropic_key", r"sk-ant-[a-zA-Z0-9\-_]{80,}", "critical", "Anthropic API key"),
    SecretPattern("openrouter_key", r"sk-or-v1-[a-zA-Z0-9]{60,}", "critical", "OpenRouter API key"),
    SecretPattern("private_key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "critical", "Private key"),
    SecretPattern("postgres_url", r"postgres(?:ql)?://[^:]+:[^@]+@", "critical", "PostgreSQL connection"),
    SecretPattern("aws_access_key", r"AKIA[0-9A-Z]{16}", "critical", "AWS Access Key"),
    SecretPattern("github_token", r"gh[pousr]_[a-zA-Z0-9]{36,}", "critical", "GitHub Token"),
    SecretPattern("slack_token", r"xox[baprs]-[a-zA-Z0-9\-]{10,}", "critical", "Slack Token"),
    SecretPattern("bearer_token", r"Bearer\s+[a-zA-Z0-9\-_\.]{20,}", "high", "Bearer Token"),
    SecretPattern("telegram_bot_token", r"\d{8,10}:[a-zA-Z0-9_\-]{35}", "high", "Telegram Bot Token"),
    SecretPattern("jwt_token", r"eyJ[a-zA-Z0-9_\-]+\.eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+", "high", "JWT Token"),
    SecretPattern("password_assign", r"(?:password|passwd|pwd)\s*[=:]\s*['\"]([^'\"]{6,})['\"]", "high", "Password"),
]


@dataclass
class SecretFinding:
    file: Path
    line: int
    column: int
    pattern_name: str
    severity: str
    description: str
    masked_value: str

    def to_dict(self) -> dict:
        return {
            "file": str(self.file),
            "line": self.line,
            "column": self.column,
            "pattern": self.pattern_name,
            "severity": self.severity,
            "description": self.description,
            "masked": self.masked_value,
        }


@dataclass
class ScanResult:
    ok: bool
    files_scanned: int
    findings: List[SecretFinding] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    elapsed: float = 0.0
    report: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "files_scanned": self.files_scanned,
            "total_findings": len(self.findings),
            "by_severity": {
                "critical": len([f for f in self.findings if f.severity == "critical"]),
                "high": len([f for f in self.findings if f.severity == "high"]),
                "medium": len([f for f in self.findings if f.severity == "medium"]),
                "low": len([f for f in self.findings if f.severity == "low"]),
            },
            "findings": [f.to_dict() for f in self.findings],
            "errors": self.errors,
            "elapsed": self.elapsed,
        }


class SecretScanner:
    SCAN_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
        ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
        ".env", ".properties", ".sh", ".bash", ".md", ".txt",
    }

    SKIP_DIRS = {
        ".git", ".github", ".venv", "venv", "node_modules",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        ".vault", ".secrets", ".ssh", ".cache", ".local",
        "_attic", "_archive", "archive", "backups", "backup",
        "dist", "build", ".eggs",
    }

    SKIP_FILES = {".env.example", "secrets.env.example"}
    MAX_FILE_SIZE_MB = 5

    def __init__(self, root: str = "/public", patterns=None, min_severity: str = "low"):
        self.root = Path(root).resolve()
        self.patterns = patterns or DEFAULT_PATTERNS
        self.min_severity_level = {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(min_severity, 0)
        self.stats = {"files_scanned": 0, "errors": 0}

    def scan(self, target_dir: Optional[str] = None, extensions: Optional[Set[str]] = None) -> ScanResult:
        start = time.time()
        scan_dir = self.root / target_dir if target_dir else self.root

        if not scan_dir.exists():
            return ScanResult(ok=False, files_scanned=0, errors=[f"Not found: {scan_dir}"], elapsed=time.time() - start)

        findings: List[SecretFinding] = []
        errors: List[str] = []
        exts = extensions or self.SCAN_EXTENSIONS

        for path in scan_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(part in self.SKIP_DIRS for part in path.parts):
                continue
            if path.name in self.SKIP_FILES:
                continue
            if path.suffix.lower() not in exts and path.name != ".env":
                continue

            try:
                if path.stat().st_size > self.MAX_FILE_SIZE_MB * 1024 * 1024:
                    continue
                findings.extend(self._scan_file(path))
                self.stats["files_scanned"] += 1
            except Exception as e:
                errors.append(f"{path}: {str(e)[:80]}")

        findings = [f for f in findings if self._sev_level(f.severity) >= self.min_severity_level]
        findings.sort(key=lambda f: self._sev_level(f.severity), reverse=True)

        result = ScanResult(ok=True, files_scanned=self.stats["files_scanned"], findings=findings, errors=errors, elapsed=time.time() - start)
        result.report = self._format_report(result)
        return result

    def scan_text(self, text: str, source: str = "<text>") -> List[SecretFinding]:
        findings: List[SecretFinding] = []
        for line_num, line in enumerate(text.split("\n"), 1):
            for pattern in self.patterns:
                try:
                    for match in pattern.compiled().finditer(line):
                        findings.append(self._make_finding(Path(source), line_num, match.start(), match.group(0), pattern))
                except re.error:
                    continue
        return findings

    def _scan_file(self, path: Path) -> List[SecretFinding]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            return []
        return self.scan_text(content, str(path))

    def _make_finding(self, path, line, col, value, pattern) -> SecretFinding:
        masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
        return SecretFinding(path, line, col, pattern.name, pattern.severity, pattern.description, masked)

    def _sev_level(self, sev: str) -> int:
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(sev, 0)

    def _format_report(self, result: ScanResult) -> str:
        lines = [
            "=" * 60,
            "🔐 SecretScanner Report",
            "=" * 60,
            f"📁 Files scanned:  {result.files_scanned:>6d}",
            f"🔍 Secrets found:  {len(result.findings):>6d}",
            f"⏱️  Elapsed:        {result.elapsed:>6.2f}s",
            "=" * 60,
        ]
        icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
        if result.findings:
            lines.append("\n📋 Findings:")
            for i, f in enumerate(result.findings[:20], 1):
                lines.append(f"\n  {i}. {icons[f.severity]} [{f.severity.upper()}] {f.description}")
                lines.append(f"     📄 {f.file}:{f.line}")
                lines.append(f"     🔒 {f.masked_value}")
        return "\n".join(lines)


def scan_for_secrets(root: str = "/public", target_dir: Optional[str] = None, min_severity: str = "low") -> Dict[str, Any]:
    scanner = SecretScanner(root=root, min_severity=min_severity)
    return scanner.scan(target_dir=target_dir).to_dict()


secret_scanner = SecretScanner()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/public")
    parser.add_argument("--dir")
    parser.add_argument("--severity", default="low")
    args = parser.parse_args()
    scanner = SecretScanner(root=args.root, min_severity=args.severity)
    result = scanner.scan(target_dir=args.dir)
    print(result.report)
