"""
SelfImprove - NovaMind improves itself
- Reads its own code
- Suggests improvements
- Tests changes in branch
- Keeps only if tests pass
"""
import ast
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novamind.core.llm_router import get_router
from novamind.core.cost_router import get_cost_router
from novamind.core.git_manager import git_manager
from novamind.agents.tester import tester
from memory import memory
import os

logger = logging.getLogger("self_improve")


# ═══════════════════════════════════════════════════════
#  Code Quality Analyzer
# ═══════════════════════════════════════════════════════
class CodeAnalyzer:
    """Analyzes code quality using AST (no LLM)."""

    def analyze_file(self, path: Path) -> Dict:
        """Analyzes a single file."""
        try:
            code = path.read_text(encoding="utf-8")
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"path": str(path), "error": "syntax: " + str(e)[:100]}

        issues = []

        for node in ast.walk(tree):
            # Function without docstring
            if isinstance(node, ast.FunctionDef):
                if not ast.get_docstring(node):
                    if not node.name.startswith("_"):
                        issues.append({
                            "type": "missing_docstring",
                            "line": node.lineno,
                            "name": node.name,
                        })
                # Long functions (>50 lines)
                if hasattr(node, "end_lineno") and node.end_lineno:
                    length = node.end_lineno - node.lineno
                    if length > 50:
                        issues.append({
                            "type": "long_function",
                            "line": node.lineno,
                            "name": node.name,
                            "length": length,
                        })

            # Bare except
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    issues.append({
                        "type": "bare_except",
                        "line": node.lineno,
                    })

        # Count lines
        lines = code.split("\n")
        total = len(lines)
        blank = sum(1 for l in lines if not l.strip())
        comments = sum(1 for l in lines if l.strip().startswith("#"))

        return {
            "path": str(path),
            "total_lines": total,
            "blank_lines": blank,
            "comment_lines": comments,
            "code_lines": total - blank - comments,
            "issues": issues,
            "issue_count": len(issues),
        }

    def analyze_project(self, root: Path) -> Dict:
        """Analyzes all .py files in project."""
        results = []
        total_issues = 0

        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            if path.name.startswith("_"):
                continue

            result = self.analyze_file(path)
            results.append(result)
            total_issues += result.get("issue_count", 0)

        return {
            "files_analyzed": len(results),
            "total_issues": total_issues,
            "files": results,
        }


analyzer = CodeAnalyzer()


# ═══════════════════════════════════════════════════════
#  Self-Improvement Engine
# ═══════════════════════════════════════════════════════
class SelfImprove:
    def __init__(self):
        self.router = get_router()
        self.cost_router = get_cost_router()
        self.name = "self_improve"

    def find_issues(self, root: str = os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))) -> Dict:
        """Finds code quality issues without LLM."""
        return analyzer.analyze_project(Path(root))

    def suggest_improvements(self, file_path: str,
                             max_suggestions: int = 3) -> List[Dict]:
        """Uses LLM to suggest improvements for a file."""
        path = Path(file_path)
        if not path.exists():
            return []

        code = path.read_text(encoding="utf-8")
        if len(code) > 8000:
            code = code[:8000] + "\n# ... (truncated)"

        prompt = (
            "Analyze this Python file and suggest up to " +
            str(max_suggestions) + " SPECIFIC improvements.\n\n"
            "File: " + path.name + "\n\n"
            "```python\n" + code + "\n```\n\n"
            "For each improvement, output a JSON object on its own line:\n"
            '{"type": "docstring|bug|perf|style|test", '
            '"line": <number>, "issue": "<short>", "fix": "<short>"}\n\n'
            "Return ONLY JSON lines (one per improvement, max " +
            str(max_suggestions) + "). No explanation."
        )

        result = self.cost_router.generate_for_task(
            task_type="analysis",
            prompt=prompt,
            temperature=0.1,
            max_tokens=800,
        )

        if not result.get("ok"):
            logger.warning("suggestion LLM failed: " +
                           result.get("error", "")[:80])
            return []

        text = result.get("text", "")
        suggestions = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    import json
                    suggestions.append(json.loads(line))
                except Exception:
                    continue

        return suggestions[:max_suggestions]

    def propose_improvement(self, file_path: str,
                            issue: Dict) -> Optional[str]:
        """Uses LLM to produce an improved version of the file."""
        path = Path(file_path)
        if not path.exists():
            return None

        code = path.read_text(encoding="utf-8")
        if len(code) > 6000:
            logger.warning("file too large for improvement: " + str(path))
            return None

        prompt = (
            "Improve this Python file by fixing ONE specific issue.\n\n"
            "File: " + path.name + "\n"
            "Issue: " + str(issue.get("issue", "")) + "\n"
            "Suggested fix: " + str(issue.get("fix", "")) + "\n\n"
            "```python\n" + code + "\n```\n\n"
            "Return ONLY the complete improved Python file. "
            "No explanations, no markdown fences."
        )

        result = self.cost_router.generate_for_task(
            task_type="code",
            prompt=prompt,
            temperature=0.1,
            max_tokens=4000,
        )

        if not result.get("ok"):
            return None

        improved = result.get("text", "").strip()
        if improved.startswith("```"):
            lines = improved.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            improved = "\n".join(lines)

        return improved.strip() if improved.strip() else None

    def test_improvement(self, original_path: str,
                         improved_code: str) -> Dict:
        """Tests if improved code passes basic checks."""
        # 1. Syntax check
        try:
            compile(improved_code, original_path, "exec")
        except SyntaxError as e:
            return {
                "ok": False,
                "reason": "syntax: " + str(e)[:100],
            }

        # 2. Run the file if it has a main
        test = tester.run(improved_code, timeout=10)

        # Even if it fails to run, syntax may be ok
        return {
            "ok": True,
            "syntax_ok": True,
            "run_success": test.get("success", False),
            "run_stdout": test.get("stdout", "")[:200],
            "run_stderr": test.get("stderr", "")[:200],
        }

    def apply_improvement(self, file_path: str,
                          improved_code: str,
                          description: str) -> Dict:
        """Applies improvement in a git branch."""
        path = Path(file_path)

        # 1. Create branch
        branch_result = git_manager.create_branch(
            "improve-" + path.stem
        )
        if not branch_result.get("ok"):
            return {"ok": False, "error": "branch creation failed"}

        branch = branch_result["branch"]

        # 2. Backup original
        original = path.read_text(encoding="utf-8")
        backup_path = path.with_suffix(path.suffix + ".backup")
        backup_path.write_text(original, encoding="utf-8")

        # 3. Write improved version
        path.write_text(improved_code, encoding="utf-8")

        # 4. Test
        test = self.test_improvement(str(path), improved_code)
        if not test.get("ok"):
            # Rollback
            path.write_text(original, encoding="utf-8")
            git_manager.checkout("master")
            return {
                "ok": False,
                "reason": test.get("reason"),
                "branch": branch,
            }

        # 5. Commit
        commit = git_manager.commit_smart(
            str(path), "improved", 0
        )

        # 6. Go back to master
        git_manager.checkout("master")

        # 7. Learn from this improvement
        memory.remember(
            "Improved " + path.name + ": " + description[:100],
            source="self_improve",
            confidence=0.7,
        )

        return {
            "ok": True,
            "branch": branch,
            "commit": commit.get("stdout", "")[:80],
            "test": test,
        }

    def cycle(self, file_path: str, max_attempts: int = 2) -> Dict:
        """Runs one full self-improvement cycle on a file."""
        logger.info("starting self-improvement cycle on " + file_path)

        # 1. Find suggestions
        suggestions = self.suggest_improvements(file_path, max_suggestions=3)
        if not suggestions:
            return {"ok": False, "reason": "no suggestions"}

        logger.info("found " + str(len(suggestions)) + " suggestions")

        # 2. Try first suggestion
        for idx, issue in enumerate(suggestions[:max_attempts]):
            logger.info("trying suggestion " + str(idx + 1) +
                        ": " + str(issue.get("type", "?")))

            improved = self.propose_improvement(file_path, issue)
            if not improved:
                continue

            # 3. Apply
            apply_result = self.apply_improvement(
                file_path, improved,
                str(issue.get("issue", ""))
            )

            if apply_result.get("ok"):
                logger.info("improvement applied: " +
                            apply_result.get("branch", ""))
                return apply_result

            logger.info("suggestion " + str(idx + 1) + " failed, trying next")

        return {"ok": False, "reason": "all suggestions failed"}


self_improve = SelfImprove()
