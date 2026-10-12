"""QualityGuardian — يضمن معايير الجودة."""
from novamind.base import BaseAgent
import ast
from pathlib import Path
import re
import logging

log = logging.getLogger("QualityGuardian")


class QualityGuardian(BaseAgent):
    NAME = "quality"
    DESCRIPTION = "يفرض معايير الجودة ويراجع القرارات"
    ROLE = "executive"
    LEVEL = 4
    CAPABILITIES = [
        "define_standards", "check_compliance",
        "measure_quality", "enforce_rules",
        "approve_release", "review_code_quality",
        "lint", "guard",
    ]

    # ═══ معايير الجودة ═══
    STANDARDS = {
        "max_file_lines": 500,
        "max_function_lines": 50,
        "max_complexity": 10,
        "min_docstring_ratio": 0.3,
        "no_todos": False,  # TODO مسموح
        "no_bare_except": True,
    }

    def _register_tools(self):
        self.tools = {
            "check_file": self._check_file,
            "measure": self._measure_quality,
        }

    async def handle(self, task):
        action = task.get("action", "").lower()
        params = task.get("params", {})

        try:
            if "check" in action and "file" in action:
                return self._check_file(params)

            if "measure" in action or "quality" in action:
                return self._measure_quality(params)

            if "compliance" in action or "lint" in action:
                return self._check_file(params)

            if "approve" in action:
                return self._approve(params)

            return {"ok": True, "result": f"Quality: {action}"}

        except Exception as e:
            log.exception("QualityGuardian failed")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def _check_file(self, params):
        """افحص ملف."""
        path = params.get("path")
        if not path:
            return {"ok": False, "error": "no path"}

        p = Path(path)
        if not p.exists():
            return {"ok": False, "error": "file not found"}

        content = p.read_text()
        lines = content.split("\n")

        issues = []

        # 1. حجم الملف
        if len(lines) > self.STANDARDS["max_file_lines"]:
            issues.append({
                "type": "file_too_large",
                "value": len(lines),
                "limit": self.STANDARDS["max_file_lines"],
            })

        # 2. bare except
        if self.STANDARDS["no_bare_except"]:
            if re.search(r'except\s*:', content):
                issues.append({"type": "bare_except"})

        # 3. syntax
        try:
            ast.parse(content)
        except SyntaxError as e:
            issues.append({"type": "syntax_error", "line": e.lineno, "msg": e.msg})

        # 4. Docstring ratio
        try:
            tree = ast.parse(content)
            funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            with_doc = sum(1 for f in funcs if ast.get_docstring(f))
            doc_ratio = with_doc / len(funcs) if funcs else 1.0

            if doc_ratio < self.STANDARDS["min_docstring_ratio"]:
                issues.append({
                    "type": "low_docstring_ratio",
                    "value": doc_ratio,
                    "limit": self.STANDARDS["min_docstring_ratio"],
                })
        except Exception:
            pass

        return {
            "ok": True,
            "result": {
                "path": str(path),
                "lines": len(lines),
                "issues": issues,
                "passed": len(issues) == 0,
            },
        }

    def _measure_quality(self, params):
        """قيّم جودة الملفات."""
        root = Path(params.get("path", "/public/hive"))
        py_files = list(root.rglob("*.py"))

        total_files = 0
        passed = 0
        failed = 0

        for f in py_files[:50]:  # حد أقصى
            if "__pycache__" in str(f):
                continue
            result = self._check_file({"path": str(f)})
            total_files += 1
            if result["ok"] and result["result"]["passed"]:
                passed += 1
            else:
                failed += 1

        score = (passed / total_files * 100) if total_files > 0 else 0

        return {
            "ok": True,
            "result": {
                "total_files": total_files,
                "passed": passed,
                "failed": failed,
                "score": round(score, 1),
            },
        }

    def _approve(self, params):
        """اعتمد إصدار."""
        quality = self._measure_quality(params)
        if quality["ok"] and quality["result"]["score"] >= 80:
            return {"ok": True, "result": {"approved": True, "score": quality["result"]["score"]}}
        return {"ok": True, "result": {"approved": False, "reason": "quality below 80%", "score": quality["result"]["score"]}}

# Auto-instance for registry
quality_guardian = QualityGuardian()
