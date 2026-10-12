"""Vue Agent — Detects Vue anti-patterns."""
import logging
import re
from typing import Dict, List

logger = logging.getLogger("agents.vue_agent")


class VueAgent:

    def __init__(self):
        self.name = "vue"
    """Detects Vue issues."""

    PATTERNS = {
        "reactivity": [
            (r'this\.\w+\s*=(?!=)', "Direct state mutation — use $set"),
            (r'Vue\.set\s*\([^)]*\)[^;]*(?:\n.*){10}', "Heavy Vue.set usage"),
        ],
        "lifecycle": [
            (r'beforeDestroy', "beforeDestroy — use beforeUnmount (Vue 3)"),
            (r'destroyed\s*\(\s*\)', "destroyed — use unmounted (Vue 3)"),
        ],
        "computed": [
            (r'computed:\s*\{[\s\S]{0,500}methods:\s*\{', "Computed and methods combined — verify"),
        ],
        "perf": [
            (r'v-for\s*=.*v-if\s*=', "v-for with v-if — bad perf"),
            (r'v-for\s*=.*(?!:key)', "v-for without :key"),
        ],
        "keys": [
            (r'v-for\s*=\s*"[^"]+"[^>]*(?!:key)', "Missing :key in v-for"),
        ],
        "vue3": [
            (r'Vue\.component\s*\(', "Vue 3: use app.component()"),
            (r'new\s+Vue\s*\(', "Vue 3: use createApp()"),
            (r'Vue\.prototype', "Vue 3: use app.config.globalProperties"),
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
                            "severity": "medium",
                            "description": desc,
                            "snippet": line.strip()[:100],
                        })

        return {
            "ok": not issues,
            "verdict": "issues" if issues else "ok",
            "total": len(issues),
            "issues": issues,
        }


vue_agent = VueAgent()
__all__ = ["VueAgent", "vue_agent"]
