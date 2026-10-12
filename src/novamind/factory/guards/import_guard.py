"""Import Guard — يتحقق من توفر imports."""
from __future__ import annotations
from typing import Dict, Any, List
import ast
import importlib.util

from novamind.factory.guards.base import GuardResult


# حزم معروفة في بيئة NovaMind
KNOWN_PACKAGES = {
    "fastapi", "uvicorn", "sqlalchemy", "pydantic",
    "pytest", "ruff", "mypy", "bandit",
    "requests", "httpx", "aiohttp",
    "telegram", "jinja2", "yaml", "redis",
    "numpy", "pandas",
}

# stdlib معروفة (نستخدم مجموعة جزئية شائعة)
STDLIB_TOP = {
    "os", "sys", "json", "re", "time", "datetime", "pathlib",
    "typing", "dataclasses", "enum", "abc", "collections",
    "itertools", "functools", "subprocess", "shutil", "hashlib",
    "sqlite3", "logging", "asyncio", "threading", "uuid",
    "tempfile", "random", "math", "io", "traceback",
    "importlib", "contextlib", "shlex", "secrets", "string",
    "argparse", "unittest", "ast",
}


class ImportGuard:
    name = "import_guard"

    def check(self, data: Dict[str, Any]) -> GuardResult:
        result = GuardResult(passed=True, guard_name=self.name)
        code = data.get("code")
        if not code:
            return result

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return result  # CodeGuard يعالج

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and not node.level:
                    imports.add(node.module.split(".")[0])

        # صنّف
        unknown = []
        local = {"hive", "core", "app", "agents"}

        for pkg in imports:
            if pkg in STDLIB_TOP:
                continue
            if pkg in KNOWN_PACKAGES:
                continue
            if pkg in local:
                continue
            # افحص إذا مثبّت
            try:
                spec = importlib.util.find_spec(pkg)
                if spec is None:
                    unknown.append(pkg)
            except (ImportError, ValueError):
                unknown.append(pkg)

        for pkg in unknown:
            result.add_warning(f"unknown package: {pkg}")

        result.details["imports"] = sorted(imports)
        result.details["unknown"] = unknown
        return result
