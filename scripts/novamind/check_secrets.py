#!/usr/bin/env python3
"""
Pre-commit hook: block hardcoded secrets in Python files.
Offline-safe: pure Python, no external dependencies.

Usage:
    python3 scripts/check_secrets.py file1.py file2.py
"""
import re
import sys
from pathlib import Path

# Match BOTH real and dummy keys (comprehensive)
PATTERNS = [
    # Gemini (real format: AIzaSy + 33 chars)
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "Gemini"),
    # OpenAI
    (re.compile(r"sk-[0-9A-Za-z]{20,}"), "OpenAI"),
    # Groq
    (re.compile(r"gsk_[0-9A-Za-z]{20,}"), "Groq"),
    # Anthropic
    (re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}"), "Anthropic"),
    # OpenRouter
    (re.compile(r"sk-or-[0-9A-Za-z_\-]{20,}"), "OpenRouter"),
    # Generic placeholders
    (re.compile(r"YOUR_API_KEY[_A-Z]*HERE", re.IGNORECASE), "Placeholder"),
    (re.compile(r"INSERT_API_KEY[_A-Z]*HERE", re.IGNORECASE), "Placeholder"),
    (re.compile(r"<your[_-]api[_-]key>", re.IGNORECASE), "Placeholder"),
]


def check_file(fname: str):
    """Return list of (line_num, kind)."""
    path = Path(fname)
    if not path.exists() or path.suffix != ".py":
        return []
    
    # Skip test files
    if "test" in str(path).lower():
        return []
    
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []
    
    findings = []
    for line_num, line in enumerate(content.split("\n"), 1):
        # Skip lines that clearly use env vars
        if "os.environ" in line or "getenv" in line or "settings." in line:
            continue
        for pattern, kind in PATTERNS:
            if pattern.search(line):
                findings.append((line_num, kind))
    return findings


def main():
    files = sys.argv[1:]
    if not files:
        return 0
    
    blocked = False
    for fname in files:
        for line_num, kind in check_file(fname):
            print(f"BLOCKED: {fname}:{line_num} hardcoded {kind} key")
            blocked = True
    
    if blocked:
        print("")
        print("=" * 60)
        print("Commit blocked: hardcoded API keys detected.")
        print("Use: KEY = os.environ.get('KEY_NAME')")
        print("=" * 60)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
