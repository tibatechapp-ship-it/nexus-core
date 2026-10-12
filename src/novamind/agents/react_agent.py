"""React Agent — Detects React anti-patterns."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.react_agent")


class ReactAgent:

    def __init__(self):
        self.name = "react"
    """Detects React issues."""

    PATTERNS = {
        "hooks_rules": [
            (r'if\s*\([^)]*\)\s*\{[^}]*use[A-Z]\w*\(', "Hook inside condition — violates rules"),
            (r'for\s*\([^)]*\)\s*\{[^}]*use[A-Z]\w*\(', "Hook inside loop"),
            (r'use[A-Z]\w*\s*\(\s*\)[^;]*\n[^}]*use[A-Z]\w*\(\s*\)[^;]*\n[^}]*if\s*\(', "Hooks after condition"),
        ],
        "perf": [
            (r'map\s*\([^)]*\)\s*=>\s*<[^>]+>', "Consider React.memo for list items"),
            (r'useEffect\s*\(\s*\(\)\s*=>\s*\{[^}]*\}\s*\)(?!\s*,\s*\[)', "useEffect without deps array"),
            (r'useEffect\s*\(\s*\(\)\s*=>\s*\{[^}]*\},\s*\[\s*\]\s*\)[^;]*useEffect', "Multiple empty deps"),
        ],
        "state": [
            (r'useState\s*\(\s*\{\s*\}\s*\)', "UseState with empty object — use null"),
            (r'setState\s*\(\s*\{\s*\.\.\.', "setState with spread — use callback"),
        ],
        "keys": [
            (r'\.map\s*\([^)]*\)\s*=>\s*<[^>]+>(?![\s\S]{0,200}key\s*=)', "Missing key in list"),
            (r'key\s*=\s*\{\s*index\s*\}', "Array index as key — anti-pattern"),
        ],
        "components": [
            (r'class\s+\w+\s+extends\s+(?:React\.)?Component', "Class component — consider hooks"),
            (r'componentWillMount', "componentWillMount deprecated"),
            (r'componentWillReceiveProps', "componentWillReceiveProps deprecated"),
        ],
        "dangerous": [
            (r'dangerouslySetInnerHTML', "dangerouslySetInnerHTML — XSS risk"),
        ],
    }

    def analyze(self, code: str, filename: str = "") -> Dict:
        if not code:
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        issues = []
        lines = code.split("\n")

        for category, patterns in self.PATTERNS.items():
            for pattern, desc in patterns:
                try:
                    regex = re.compile(pattern, re.MULTILINE)
                except re.error:
                    continue
                for i, line in enumerate(lines, 1):
                    if line.strip().startswith(("//", "/*", "*")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "category": category,
                            "severity": "high" if category in ("hooks_rules", "dangerous") else "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


react_agent = ReactAgent()
__all__ = ["ReactAgent", "react_agent"]
