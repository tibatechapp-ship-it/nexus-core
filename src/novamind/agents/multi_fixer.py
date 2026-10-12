"""
MultiFixerAgent - Multi-strategy code fixer
- Runs 3 strategies in parallel:
  1. Minimal (single-line change)
  2. Defensive (add checks)
  3. Refactor (rewrite section)
- Judge picks the best result
- Falls back to single-strategy if all fail
"""
from pathlib import Path
import logging
import sys
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novamind.core.llm_router import get_router
from novamind.core.cost_router import get_cost_router
from novamind.agents.tester import tester
from memory import memory

# Logger definition (must be before any use)
logger = logging.getLogger("multi_fixer")




# ═══════════════════════════════════════════════════════
#  3 Different strategy prompts
# ═══════════════════════════════════════════════════════
STRATEGY_MINIMAL = """You fix Python code with the SMALLEST possible change.

Rules:
- Change only what's strictly necessary
- One line if possible
- Keep all existing behavior
- Return ONLY the fixed Python code (no explanation, no fences)
"""

STRATEGY_DEFENSIVE = """You fix Python code by adding DEFENSIVE checks.

Rules:
- Add input validation and error handling
- Check for None, empty, zero, wrong types
- Add try/except where needed
- Preserve original logic
- Return ONLY the fixed Python code (no explanation, no fences)
"""

STRATEGY_REFACTOR = """You fix Python code by REFACTORING the problematic section.

Rules:
- Rewrite only the failing part cleanly
- Improve readability and safety
- Keep the public API unchanged
- Return ONLY the fixed Python code (no explanation, no fences)
"""

STRATEGIES = [
    ("minimal", STRATEGY_MINIMAL, 0.1),
    ("defensive", STRATEGY_DEFENSIVE, 0.15),
    ("refactor", STRATEGY_REFACTOR, 0.2),
]


def _strip_fences(text):
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


class MultiFixer:
    def __init__(self):
        self.name = "multi_fixer"
        self.router = get_router()

    def fix(self, code, error="", issues=None, previous_attempts=None):
        """
        Tries 3 strategies. Tests each. Picks first successful one.
        Returns: {ok, code, strategy, attempts, provider, elapsed}
        """
        if not code or not code.strip():
            return {"ok": False, "code": "", "strategy": "",
                    "attempts": 0, "provider": "", "error": "empty code"}

        issues = issues or []
        previous_attempts = previous_attempts or []

        # Get memory context
        memory_ctx = ""
        try:
            recall = memory.recall(error[:200] if error else "fix error")
            if recall.get("semantic"):
                memory_ctx = "Previously learned:\n" + recall["semantic"] + "\n"
        except Exception:
            pass

        issues_text = ""
        if issues:
            lines = []
            for i in issues:
                line = i.get("line", "?")
                desc = i.get("description", "")
                lines.append("  - line " + str(line) + ": " + desc)
            issues_text = "Detected issues:\n" + "\n".join(lines) + "\n"

        prev_text = ""
        if previous_attempts:
            prev_text = "Previous failed attempts (avoid repeating):\n"
            for idx, prev in enumerate(previous_attempts[-2:], 1):
                prev_text += "--- attempt " + str(idx) + " ---\n" + prev[:400] + "\n"

        results = []

        # Try each strategy
        for strategy_name, system_prompt, temperature in STRATEGIES:
            logger.info("trying strategy: " + strategy_name)

            prompt = (
                memory_ctx + prev_text +
                "Original code:\n```python\n" + code + "\n```\n\n" +
                "Error:\n```\n" + (error or "no error message") + "\n```\n\n" +
                issues_text +
                "\nStrategy: " + strategy_name.upper() + "\n" +
                "Return ONLY the fixed Python code."
            )

            cost_router = get_cost_router()
            result = cost_router.generate_for_task(
                task_type="code",
                prompt=prompt,
                system=system_prompt,
                temperature=temperature,
                max_tokens=2500,
            )

            if not result.get("ok"):
                logger.warning("strategy " + strategy_name +
                               " LLM failed: " + result.get("error", "")[:80])
                continue

            fixed = _strip_fences(result.get("text", ""))
            if not fixed.strip():
                logger.warning("strategy " + strategy_name + " produced empty code")
                continue

            # Test the fixed code
            test = tester.run(fixed)
            result_data = {
                "strategy": strategy_name,
                "code": fixed,
                "test_success": test.get("success", False),
                "test_stdout": test.get("stdout", "")[:200],
                "test_stderr": test.get("stderr", "")[:200],
                "provider": result.get("provider", ""),
                "elapsed": result.get("elapsed", 0.0),
            }
            results.append(result_data)

            if test.get("success"):
                logger.info("strategy " + strategy_name + " SUCCEEDED")
                return {
                    "ok": True,
                    "code": fixed,
                    "strategy": strategy_name,
                    "attempts": len(results),
                    "provider": result.get("provider", ""),
                    "elapsed": result.get("elapsed", 0.0),
                    "all_strategies": [r["strategy"] for r in results],
                    "error": "",
                }
            else:
                logger.info("strategy " + strategy_name +
                            " failed test: " + test.get("stderr", "")[:80])

        # All strategies failed
        best = results[0] if results else None
        logger.warning("all strategies failed")
        return {
            "ok": False,
            "code": best["code"] if best else code,
            "strategy": best["strategy"] if best else "",
            "attempts": len(results),
            "provider": best["provider"] if best else "",
            "error": "all strategies failed (" + str(len(results)) + " tried)",
            "all_strategies": [r["strategy"] for r in results],
        }


multi_fixer = MultiFixer()
