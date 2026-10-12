"""
Test Runner - Generates, runs, and validates tests
Stronger than Copilot: includes coverage + mutation ideas
"""
import logging
import re
import sys
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novamind.core.llm_router import get_router
from novamind.agents.test_generator import test_generator

logger = logging.getLogger("agents.test_runner")


class TestRunner:
    def __init__(self):
        self.router = get_router()
        self.name = "test_runner"

    def run_pytest(self, test_code: str, source_file: str = "source.py",
                   source_code: str = "") -> Dict:
        """
        Runs pytest tests.
        If source_code provided, creates both files in temp dir.
        """
        tmp_dir = tempfile.mkdtemp(prefix="nova_test_", dir=f"{os.environ.get('NOVAMIND_HOME', str(Path(__file__).resolve().parent.parent))}/workspace")

        try:
            # Write source file
            source_path = Path(tmp_dir) / source_file
            if source_code:
                source_path.write_text(source_code, encoding="utf-8")

            # Determine test filename
            test_path = Path(tmp_dir) / ("test_" + source_file)

            # Write test file
            test_path.write_text(test_code, encoding="utf-8")

            # Install pytest if needed
            try:
                subprocess.run(
                    ["python3", "-m", "pytest", "--version"],
                    capture_output=True, timeout=5,
                )
            except Exception:
                return {"ok": False, "error": "pytest not installed"}

            # Run pytest
            result = subprocess.run(
                ["python3", "-m", "pytest", str(test_path), "-v", "--tb=short"],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = (result.stdout or "") + (result.stderr or "")

            # Parse pytest output
            passed = 0
            failed = 0
            errors = 0

            match = re.search(r'(\d+) passed', output)
            if match:
                passed = int(match.group(1))

            match = re.search(r'(\d+) failed', output)
            if match:
                failed = int(match.group(1))

            match = re.search(r'(\d+) error', output)
            if match:
                errors = int(match.group(1))

            return {
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "output": output[-3000:],
                "total": passed + failed + errors,
            }

        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "test timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        finally:
            # Cleanup
            try:
                import shutil
                shutil.rmtree(tmp_dir)
            except Exception:
                pass

    def generate_and_test(self, code: str, filename: str) -> Dict:
        """
        Full cycle: generate tests, run them, report results.
        """
        logger.info(f"generate and test: {filename}")

        # 1. Generate tests
        gen_result = test_generator.generate(code, filename)
        if not gen_result.get("ok"):
            return {
                "ok": False,
                "stage": "generation",
                "error": gen_result.get("error", "")[:100],
            }

        tests_code = gen_result.get("tests", "")
        if not tests_code.strip():
            return {"ok": False, "stage": "generation", "error": "empty tests"}

        # 2. Run tests
        run_result = self.run_pytest(tests_code, filename, code)

        return {
            "ok": run_result.get("ok", False),
            "stage": "complete",
            "test_code": tests_code,
            "test_file": gen_result.get("test_filename", "?"),
            "framework": gen_result.get("framework", "pytest"),
            "functions_tested": gen_result.get("functions_tested", 0),
            "run_result": run_result,
        }

    def mutation_ideas(self, code: str, filename: str) -> Dict:
        """
        Suggests mutations to test against (stronger than Copilot).
        Uses LLM to propose edge cases.
        """
        system = """You are a test engineer specializing in mutation testing.
Suggest 5 edge cases that would likely break the given code.
Return ONLY a JSON array of strings (the edge cases).
Example: ["empty input", "None value", "very large number", "unicode text", "concurrent access"]"""

        prompt = f"Code from {filename}:\n\n{code[:2000]}\n\nReturn JSON array of 5 edge cases."

        try:
            result = self.router.generate_for_task(
                task_type="analysis",
                prompt=prompt,
                system=system,
                temperature=0.3,
                max_tokens=300,
            )

            if not result.get("ok"):
                return {"ok": False, "error": "LLM failed"}

            text = result.get("text", "")
            import json
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                edges = json.loads(match.group(0))
                return {"ok": True, "edge_cases": edges[:5]}

            return {"ok": True, "edge_cases": []}
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}


test_runner = TestRunner()
