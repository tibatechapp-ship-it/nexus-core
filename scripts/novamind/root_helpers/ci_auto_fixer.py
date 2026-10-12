"""
CI Auto-Fixer — Uses AI (Groq/Gemini) to analyze CI failures.
"""
import os
import sys
import json
import re
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def read_logs(log_file: str) -> str:
    """Read logs from file."""
    if not log_file:
        return sys.stdin.read()
    p = Path(log_file)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")


def extract_errors(logs: str, max_lines: int = 150) -> str:
    """Extract error lines."""
    lines = logs.split("\n")
    errors = []
    capture = False
    for line in lines:
        if any(x in line for x in [
            "FAILED", "ERROR", "Traceback", "AssertionError",
            "PermissionError", "ImportError", "SyntaxError",
            "ModuleNotFoundError", "FileNotFoundError",
        ]):
            capture = True
        if capture:
            errors.append(line)
            if len(errors) >= max_lines:
                break
    if not errors:
        return logs[-3000:]
    return "\n".join(errors)


def try_groq(errors: str) -> str:
    """Try Groq API."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return ""
    try:
        from groq import Groq
    except ImportError:
        return ""

    try:
        client = Groq(api_key=key)
        prompt = f"""You are a CI debugging expert for Python project NovaMind v8.0.

CI failed with these errors:

Provide a fix in JSON format ONLY:
{{
  "root_cause": "1-2 sentences",
  "fix_description": "specific fix",
  "files_to_change": [{{"path": "file.py", "change": "description"}}],
  "commands": ["command1", "command2"]
}}
"""
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a CI debugging expert. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Groq failed: {e}")
        return ""


def try_gemini(errors: str) -> str:
    """Try Gemini API."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return ""
    try:
        import google.generativeai as genai
    except ImportError:
        return ""

    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        prompt = f"""You are a CI debugging expert for Python project NovaMind v8.0.

CI failed with:

Respond with JSON only:
{{
  "root_cause": "...",
  "fix_description": "...",
  "files_to_change": [{{"path": "...", "change": "..."}}],
  "commands": ["..."]
}}
"""
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"⚠️ Gemini failed: {e}")
        return ""


def parse_and_print(response: str):
    """Parse JSON response and print nicely."""
    print("\n" + "=" * 60)
    print("  AI ANALYSIS")
    print("=" * 60)
    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            print(response)
            return
        fix = json.loads(match.group(0))
        print(f"\n🔴 Root Cause:\n{fix.get('root_cause', 'N/A')}")
        print(f"\n💡 Fix:\n{fix.get('fix_description', 'N/A')}")
        print("\n📁 Files:")
        for f in fix.get("files_to_change", []):
            print(f"  - {f.get('path')}: {f.get('change')}")
        print("\n⚡ Commands:")
        for cmd in fix.get("commands", []):
            print(f"  $ {cmd}")
    except json.JSONDecodeError:
        print(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", help="Path to CI log file")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    print("=" * 60)
    print("  NovaMind CI Auto-Fixer")
    print("=" * 60)

    logs = read_logs(args.log)
    print(f"📄 Logs: {len(logs)} chars")

    if not logs.strip() or len(logs) < 100:
        print("❌ Logs too short. Skipping.")
        return 1

    errors = extract_errors(logs)
    print(f"🔍 Errors: {len(errors)} chars")

    # Try Groq first, then Gemini
    print("\n🤖 Asking AI...")
    response = try_groq(errors)
    if not response:
        print("   Groq failed, trying Gemini...")
        response = try_gemini(errors)

    if not response:
        print("❌ All AI providers failed.")
        return 1

    parse_and_print(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
