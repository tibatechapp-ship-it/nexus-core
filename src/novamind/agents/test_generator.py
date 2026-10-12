"""
Test Generator v2 — Enhanced with edge cases + coverage hints.
"""
import logging
import re
import sys
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))

logger = logging.getLogger("agents.test_generator")

SYSTEM_PROMPT = """You are an expert test engineer.
Generate comprehensive unit tests for the given code.

Rules:
- Use pytest for Python, Jest for TypeScript/JavaScript
- Test happy path + edge cases + error cases
- Include boundary tests (empty, None, max, min)
- Add brief Arabic comments describing test intent
- Return ONLY the test code (no explanation, no markdown fences)
- CRITICAL: Every function MUST have a body with at least ONE statement
- Use `pass` if a test function is empty
- Every `def test_xxx():` MUST be followed by an indented body
- Include import statements at the top
- Aim for high coverage of all branches
"""


class TestGenerator:
    def __init__(self):
        self.name = "test_generator"
        try:
            from novamind.core.llm_router import get_router
            self.router = get_router()
        except ImportError:
            self.router = None

    def generate(self, code: str, filename: str) -> Dict:
        """Generate tests for code."""
        if not self.router:
            return {"ok": False, "error": "llm_router not available"}

        # Determine framework
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "py":
            framework = "pytest"
            test_filename = "test_" + filename.replace(".py", "")
        elif ext in ("ts", "tsx", "js", "jsx"):
            framework = "jest"
            base = filename.rsplit(".", 1)[0]
            test_filename = base + ".test." + ext
        else:
            return {"ok": False, "error": f"unsupported language: {ext}"}

        # Detect functions/classes
        if ext == "py":
            funcs = re.findall(r'def\s+(\w+)\s*\(', code)
            classes = re.findall(r'class\s+(\w+)', code)
        else:
            funcs = re.findall(r'(?:function|const|let)\s+(\w+)\s*[=(]', code)
            classes = re.findall(r'class\s+(\w+)', code)

        # Filter private
        funcs = [f for f in funcs if not f.startswith("_")]

        if not funcs and not classes:
            return {"ok": False, "error": "no public functions/classes found"}

        # Build enhanced prompt
        prompt = (
            f"Generate comprehensive {framework} tests for this {ext} file: {filename}\n\n"
            f"Detected functions: {', '.join(funcs[:10])}\n"
            f"Detected classes: {', '.join(classes[:5])}\n\n"
            f"Code:\n"
            f"```\n{code[:4000]}\n```\n\n"
            f"Return ONLY the test code for {test_filename}."
        )

        try:
            result = self.router.generate_for_task(
                task_type="smart",
                prompt=prompt,
                system=SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=2500,
            )
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "")[:200]}

        tests = result.get("text", "").strip()

        # Strip markdown fences
        if tests.startswith("```"):
            lines = tests.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            tests = "\n".join(lines)

        # Verify syntax (safety)
        if ext == "py":
            import ast
            syntax_ok = False
            try:
                ast.parse(tests)
                syntax_ok = True
            except SyntaxError as e:
                logger.warning(f"generated tests have syntax error: {e.msg}")
                # محاولة إصلاح تلقائي بسيطة
                # 1. أضف pass للدوال الفارغة
                fixed_lines = []
                for line in tests.split("\n"):
                    fixed_lines.append(line)
                    # إذا كان السطر دالة بدون : في نهايته
                    if re.match(r"^\s*def\s+\w+\s*\(.*\)\s*:\s*$", line):
                        # تحقق من السطر التالي
                        continue
                tests_fixed = "\n".join(fixed_lines)
                try:
                    ast.parse(tests_fixed)
                    tests = tests_fixed
                    syntax_ok = True
                    logger.info("✅ تم إصلاح syntax تلقائياً")
                except SyntaxError:
                    pass

            if not syntax_ok:
                return {"ok": False, "error": "generated_tests_broken_syntax"}

        return {
            "ok": True,
            "tests": tests,
            "framework": framework,
            "test_filename": test_filename,
            "functions_tested": len(funcs),
            "classes_tested": len(classes),
            "provider": result.get("provider", ""),
        }


test_generator = TestGenerator()
__all__ = ["TestGenerator", "test_generator"]
