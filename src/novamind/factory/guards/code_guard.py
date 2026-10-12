"""Code Guard — يتحقق من صحة كود Python."""
from __future__ import annotations
from typing import Dict, Any
import ast
import re

from novamind.factory.guards.base import GuardResult


class CodeGuard:
    name = "code_guard"

    def check(self, data: Dict[str, Any]) -> GuardResult:
        result = GuardResult(passed=True, guard_name=self.name)
        code = data.get("code")
        if not code:
            return result  # لا كود → لا فحص

        # 1. AST parse
        try:
            tree = ast.parse(code)
            result.details["ast_ok"] = True
        except SyntaxError as e:
            result.add_error(f"SyntaxError: {e.msg} (line {e.lineno})")
            return result

        # 2. imports سليمة
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", alias.name):
                        result.add_error(f"invalid import: {alias.name}")

            if isinstance(node, ast.ImportFrom):
                if node.module and not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", node.module):
                    result.add_error(f"invalid import from: {node.module}")

        # 3. تحقق من التكرار في الكلاسات
        class_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_names.append(node.name)

        if len(class_names) != len(set(class_names)):
            dups = [n for n in class_names if class_names.count(n) > 1]
            result.add_error(f"duplicate classes: {set(dups)}")

        # 4. تحقق من الدوال المتكررة
        func_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_names.append(node.name)

        if len(func_names) != len(set(func_names)):
            dups = [n for n in func_names if func_names.count(n) > 1]
            result.add_warning(f"duplicate functions: {set(dups)}")

        # 5. عدد الأسطر
        lines = code.split("\n")
        result.details["lines"] = len(lines)
        result.details["classes"] = len(class_names)
        result.details["functions"] = len(func_names)

        return result
