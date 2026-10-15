#!/usr/bin/env python3
"""Security Scanner v4 — clean + fast."""
import asyncio
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# [FIXED PATH] Use relative imports or conftest.py instead
LOG_DIR = Path("/var/log/novamind")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "security_scanner.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("SecurityScanner")
PUBLIC = Path("/public")

# ═══ أنماط secrets ═══
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI key"),
    (r"sk-proj-[a-zA-Z0-9_-]{40,}", "OpenAI project"),
    (r"gsk_[a-zA-Z0-9]{20,}", "Groq key"),
    (r"ghp_[a-zA-Z0-9]{20,}", "GitHub PAT"),
    (r"gho_[a-zA-Z0-9]{20,}", "GitHub OAuth"),
    (r"AIza[a-zA-Z0-9_-]{35}", "Google API"),
    (r"AQ\.[a-zA-Z0-9_-]{30,}", "Gemini key"),
    (r"AKIA[0-9A-Z]{16}", "AWS Key"),
    (r"[0-9]{8,10}:[a-zA-Z0-9_-]{35}", "Telegram Bot"),
    (r"xox[baprs]-[a-zA-Z0-9-]{10,}", "Slack token"),
    (r"glpat-[a-zA-Z0-9_-]{20,}", "GitLab PAT"),
    (r"sk_live_[a-zA-Z0-9]{24,}", "Stripe Live"),
    (r"hf_[a-zA-Z0-9]{30,}", "Huggingface"),
    (r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}", "JWT"),
]

# ═══ أنماط ملفات خطرة (tracked) ═══
DANGEROUS_FILES = [
    r"^\.env$",
    r"^\.env\.[^/]+$",
    r"\.env$",
    r"^\.secrets$",
    r"^secrets/",
    r"^credentials/",
    r"id_rsa$",
    r"id_ed25519$",
    r"\.pem$",
    r"\.p12$",
    r"credentials\.json$",
    r"service[-_]account.*\.json$",
    r"^\.aws/credentials$",
]

# ═══ استثناءات (لا تُفحص) ═══
EXCLUDED = [
    r"\.example$",
    r"\.template$",
    r"\.sample$",
    r"test_",
    r"_test\.py$",
    r"_agent\.py$",
    r"_scanner\.py$",
    r"_tracker\.py$",
    r"secrets_agent\.py$",
    r"secrets\.py$",
    r"key_manager\.py$",
    r"credentials\.py$",
    r"conftest\.py$",
    r"__pycache__",
    r"\.pyc$",
]


def run(cmd, timeout=15):
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=str(PUBLIC),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def is_fake(text):
    t = text.lower()
    return any(p in t for p in [
        "xxxx", "your_", "example", "placeholder",
        "fake", "dummy", "sample", "todo",
    ])


def is_excluded(path):
    return any(re.search(pat, path) for pat in EXCLUDED)


def scan_text(text, source):
    findings = []
    for num, line in enumerate(text.split("\n")[:2000], 1):
        s = line.strip()
        if s.startswith("#") or s.startswith("//"):
            continue
        for pattern, name in SECRET_PATTERNS:
            if re.search(pattern, line) and not is_fake(line):
                findings.append({
                    "file": source, "line": num,
                    "type": name, "preview": line[:70],
                })
    return findings


def scan_staged():
    _, out, _ = run("git diff --cached --name-only", timeout=10)
    if not out:
        return []
    findings = []
    for f in out.split("\n")[:20]:
        if not f or is_excluded(f):
            continue
        fp = PUBLIC / f
        if fp.exists() and fp.is_file() and fp.stat().st_size < 200_000:
            try:
                findings += scan_text(
                    fp.read_text(encoding="utf-8", errors="ignore"), f
                )
            except Exception:
                pass
    return findings


def scan_last_commit():
    _, diff, _ = run("git show --no-color --format= -U0 HEAD", timeout=15)
    if not diff:
        return []
    findings = []
    for num, line in enumerate(diff.split("\n")[:500], 1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        for pattern, name in SECRET_PATTERNS:
            if re.search(pattern, content) and not is_fake(content):
                findings.append({
                    "source": "commit", "line": num,
                    "type": name, "preview": content[:70],
                })
    return findings


def check_gitignore():
    gi = PUBLIC / ".gitignore"
    if not gi.exists():
        return [{"issue": ".gitignore missing"}]
    content = gi.read_text()
    return [
        {"issue": f"missing pattern: {p}"}
        for p in [".env", "*.env", "*.key", "secrets/"]
        if p not in content
    ]


def check_dangerous_files():
    _, out, _ = run("git ls-files", timeout=10)
    if not out:
        return []
    issues = []
    for f in out.split("\n"):
        if not f or is_excluded(f):
            continue
        for pat in DANGEROUS_FILES:
            if re.search(pat, f):
                issues.append({"tracked": f, "reason": pat})
                break
    return issues


async def main():
    log.info("═══════════════════════════════════")
    log.info("🛡️  Security Scanner v4")
    log.info("═══════════════════════════════════")

    all_issues = []

    log.info("→ Scanning staged files...")
    staged = scan_staged()
    if staged:
        log.error(f"🚨 {len(staged)} findings in staged")
        for f in staged[:3]:
            log.error(f"  {f['file']}:{f['line']} [{f['type']}]")
    all_issues += staged

    log.info("→ Scanning last commit...")
    commit = scan_last_commit()
    if commit:
        log.error(f"🚨 {len(commit)} findings in commit")
        for f in commit[:3]:
            log.error(f"  {f['type']}: {f['preview']}")
    all_issues += commit

    log.info("→ Checking .gitignore...")
    gi = check_gitignore()
    if gi:
        log.warning(f"⚠️  {len(gi)} issues in .gitignore")
    all_issues += gi

    log.info("→ Checking tracked dangerous files...")
    dangerous = check_dangerous_files()
    if dangerous:
        log.error(f"🚨 {len(dangerous)} dangerous tracked files!")
        for d in dangerous[:3]:
            log.error(f"  {d['tracked']}")
    all_issues += dangerous

    report = {
        "at": datetime.now().isoformat(),
        "total": len(all_issues),
        "issues": all_issues,
    }
    with open(LOG_DIR / "security_reports.jsonl", "a") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")

    if all_issues:
        log.error(f"❌ {len(all_issues)} issues found")
        return 1
    log.info("✅ Clean — no issues")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
