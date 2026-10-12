"""
Migration Agent — Suggests code migrations (Py2→3, sync→async, React class→hooks).
"""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.migration_agent")


class MigrationAgent:

    def __init__(self):
        self.name = "migration"
    """Detects migration opportunities."""

    MIGRATIONS = {
        "py2_to_py3": {
            "target": "Python 3",
            "patterns": [
                (r'\bprint\s+[^(]', "print statement — use print()"),
                (r'\.iteritems\s*\(', "iteritems() → items()"),
                (r'\.iterkeys\s*\(', "iterkeys() → keys()"),
                (r'\.itervalues\s*\(', "itervalues() → values()"),
                (r'\bxrange\s*\(', "xrange() → range()"),
                (r'\bunicode\s*\(', "unicode() → str()"),
                (r'\bbasestring\b', "basestring → str"),
                (r'except\s+\w+\s*,\s*\w+:', "except X, y → except X as y"),
                (r'raise\s+\w+\s*,\s*', "raise X, y → raise X(y)"),
                (r'\.has_key\s*\(', "has_key() → in operator"),
            ],
        },
        "sync_to_async": {
            "target": "Async/Await",
            "patterns": [
                (r'^import requests\b', "requests → httpx/aiohttp in async"),
                (r'^import urllib', "urllib → httpx in async"),
                (r'time\.sleep\s*\(', "time.sleep → asyncio.sleep in async"),
            ],
        },
        "old_formatting": {
            "target": "f-strings",
            "patterns": [
                (r'["\'][^"\']*%s[^"\']*["\']\s*%', "% formatting → f-string"),
                (r'["\'][^"\']*\{\}[^"\']*["\']\s*\.format', ".format() → f-string"),
                (r'\.format\s*\(', ".format() → f-string"),
            ],
        },
        "react_class_to_hooks": {
            "target": "React Hooks",
            "patterns": [
                (r'class\s+\w+\s+extends\s+(?:React\.)?Component',
                 "Class component → function + hooks"),
                (r'this\.setState\s*\(', "setState → useState"),
                (r'componentDidMount\s*\(', "componentDidMount → useEffect"),
                (r'componentWillUnmount\s*\(', "componentWillUnmount → useEffect cleanup"),
                (r'this\.state\s*=', "this.state → useState"),
            ],
        },
        "jquery_to_vanilla": {
            "target": "Vanilla JS",
            "patterns": [
                (r'\$\([\'"]', "jQuery selector → querySelector"),
                (r'\.ajax\s*\(', "jQuery.ajax → fetch"),
                (r'\.on\s*\([\'"]click', "jQuery.on → addEventListener"),
            ],
        },
        "callback_to_promise": {
            "target": "Promises / async-await",
            "patterns": [
                (r'\.then\s*\(\s*function\s*\(', ".then(function() → .then(() =>"),
                (r'new Promise\s*\(\s*function\s*\(', "Promise(function → Promise(() =>"),
            ],
        },
    }

    def detect_lang(self, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "py":
            return "python"
        if ext in ("js", "jsx"):
            return "javascript"
        if ext in ("ts", "tsx"):
            return "typescript"
        return "any"

    def _relevant_migrations(self, lang: str) -> List[str]:
        if lang == "python":
            return ["py2_to_py3", "sync_to_async", "old_formatting"]
        if lang in ("javascript", "typescript"):
            return ["react_class_to_hooks", "jquery_to_vanilla",
                    "callback_to_promise"]
        return []

    def analyze(self, code: str, filename: str = "code.py",
                target: str = "modern") -> Dict:
        """Detect migration opportunities."""
        if not code or not code.strip():
            return {"ok": True, "verdict": "ok", "issues": [], "total": 0}

        lang = self.detect_lang(filename)
        issues = []
        lines = code.split("\n")

        for migration_name in self._relevant_migrations(lang):
            migration = self.MIGRATIONS.get(migration_name, {})
            target_name = migration.get("target", migration_name)

            for pattern, desc in migration.get("patterns", []):
                try:
                    regex = re.compile(pattern, re.MULTILINE)
                except re.error:
                    continue

                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    if stripped.startswith(("#", "//", '"""', "'''")):
                        continue
                    if regex.search(line):
                        issues.append({
                            "line": i,
                            "type": migration_name,
                            "target": target_name,
                            "severity": "info",
                            "description": desc,
                            "snippet": stripped[:100],
                        })

        # Deduplicate
        seen = set()
        unique = []
        for issue in issues:
            key = (issue["line"], issue["type"], issue["description"])
            if key not in seen:
                seen.add(key)
                unique.append(issue)

        # Group by migration type
        by_migration = {}
        for issue in unique:
            t = issue["type"]
            by_migration[t] = by_migration.get(t, 0) + 1

        return {
            "ok": len(unique) == 0,
            "verdict": "issues" if unique else "ok",
            "language": lang,
            "target": target,
            "total": len(unique),
            "by_migration": by_migration,
            "issues": unique,
        }

    def report(self, result: Dict) -> str:
        """Human-readable report."""
        if result.get("verdict") == "ok":
            return "✅ لا حاجة لترقية — الكود حديث"

        lines = [f"🔄 تقرير الترقية ({result['total']} فرصة)"]
        lines.append(f"اللغة: {result.get('language')}")
        lines.append("")

        # Group by migration
        by_type = {}
        for issue in result["issues"]:
            t = issue.get("type", "other")
            by_type.setdefault(t, []).append(issue)

        icons = {
            "py2_to_py3": "🐍",
            "sync_to_async": "⚡",
            "old_formatting": "📝",
            "react_class_to_hooks": "⚛️ ",
            "jquery_to_vanilla": "🌐",
            "callback_to_promise": "🔗",
        }

        for t, items in by_type.items():
            target = items[0].get("target", t)
            lines.append(f"{icons.get(t, '•')} {t} → {target}: {len(items)}")
            for issue in items[:5]:
                lines.append(f"   L{issue['line']}: {issue['description']}")
            lines.append("")

        return "\n".join(lines)


migration_agent = MigrationAgent()
__all__ = ["MigrationAgent", "migration_agent"]
