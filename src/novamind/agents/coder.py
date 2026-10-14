import sys  # NOVAMIND_PATH_FIX
"""
CoderAgent - Specialized agent for code generation ONLY
"""
from pathlib import Path
import logging
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sys as _sys
from pathlib import Path as _Path
_NM = _Path(__file__).resolve().parents[2]  # /public/agent/novamind
if str(_NM) not in _sys.path:
    _sys.path.insert(0, str(_NM))
from novamind.core.llm_router import get_router
from novamind.agents.tester import tester
from memory import memory

# Logger definition (must be before any use)
logger = logging.getLogger("coder")




BUILD_PROMPT = """You are a Python code builder. Your ONLY job is to output Python code.

STRICT RULES:
1. Output ONLY Python code. No explanations. No markdown fences.
2. Do NOT say "here is" or "sure" - just write the code.
3. Code must be complete and runnable.
4. Never output anything except Python code.
"""

FIX_PROMPT = """You are a Python code fixer. Output ONLY fixed Python code.

STRICT RULES:
1. Output ONLY Python code. No explanations.
2. Fix the error with MINIMAL change.
3. Keep all working functionality.
"""


class CoderAgent:
    def __init__(self):
        self.name = "coder"
        self.router = get_router()

    def _clean_output(self, text):
        if not text:
            return ""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        lines = text.split("\n")
        cleaned = []
        started = False
        for line in lines:
            stripped = line.strip()
            if not started and not stripped:
                continue
            if not started:
                is_code = (
                    stripped.startswith(("import ", "from ", "def ", "class ", "#", "@"))
                    or "=" in stripped
                    or stripped.startswith(("print(", "if ", "for ", "while ", "try:", "with "))
                )
                if is_code:
                    started = True
                else:
                    continue
            cleaned.append(line)
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        return "\n".join(cleaned)

    def build(self, request, max_fix_cycles=3, allow_test=True):
        if not request or not request.strip():
            return {"ok": False, "code": "", "attempts": 0, "provider": "", "error": "empty request"}

        logger.info("building: " + request[:80])
        memory_ctx = ""
        try:
            recall = memory.recall(request)
            if recall.get("semantic"):
                memory_ctx = "Previously learned:\n" + recall["semantic"] + "\n"
        except Exception:
            pass

        prompt = memory_ctx + "Build Python code for:\n" + request + "\n\nOutput ONLY Python code:"

        result = self.router.generate_for_task(
            task_type="code",
            prompt=prompt,
            system=BUILD_PROMPT,
            temperature=0.2,
            max_tokens=500,
        )

        if not result.get("ok"):
            return {"ok": False, "code": "", "attempts": 0, "provider": "",
                    "error": result.get("error", "router failed")}

        code = self._clean_output(result.get("text", ""))
        provider_used = result.get("provider", "")

        if not code.strip():
            return {"ok": False, "code": "", "attempts": 1, "provider": provider_used,
                    "error": "empty code generated"}

        if not allow_test:
            return {"ok": True, "code": code, "attempts": 1, "provider": provider_used, "error": ""}

        test_result = tester.run(code)
        if test_result.get("success"):
            return {"ok": True, "code": code, "attempts": 1, "provider": provider_used, "error": ""}

        last_error = test_result.get("stderr", "")
        current_code = code

        for cycle in range(1, max_fix_cycles + 1):
            logger.info("fix cycle " + str(cycle))
            fix_prompt = ("Fix this Python code:\n\n" + current_code +
                          "\n\nError:\n" + last_error[:500] +
                          "\n\nOutput ONLY the fixed Python code:")
            fix_result = self.router.generate_for_task(
                task_type="code", prompt=fix_prompt, system=FIX_PROMPT,
                temperature=0.1, max_tokens=500,
            )
            if not fix_result.get("ok"):
                break
            fixed_code = self._clean_output(fix_result.get("text", ""))
            if not fixed_code.strip():
                break
            current_code = fixed_code
            test_result = tester.run(current_code)
            if test_result.get("success"):
                return {"ok": True, "code": current_code, "attempts": cycle + 1,
                        "provider": fix_result.get("provider", provider_used), "error": ""}
            last_error = test_result.get("stderr", "")

        return {"ok": False, "code": current_code, "attempts": max_fix_cycles + 1,
                "provider": provider_used, "error": "failed to fix"}


coder = CoderAgent()

# Auto-instance for registry
coder = CoderAgent()
