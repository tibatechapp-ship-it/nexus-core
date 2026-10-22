"""Code Guardian — validates model-generated Python before delivery.

Layers:
  1. Syntax: `compile()` — catches SyntaxError cheaply.
  2. Undefined names: AST heuristic (conservative, no false positives).
  3. Missing imports: 5-lib whitelist (json, os, re, sys, csv) — auto-fixable.
  4. Repair: returns a targeted repair prompt for the LLM.

Not a linter. Not a type checker. A fast pre-flight that stops the most
common small-model failures: forgotten imports, typos in variable names,
and obviously-broken syntax.
"""
from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass, field
from typing import Optional

_AUTOFIX_LIBS: dict[str, tuple[str, ...]] = {
    "json": ("dumps", "loads", "dump", "load", "JSONDecodeError"),
    "os": ("getcwd", "listdir", "makedirs", "remove", "rename", "environ", "walk"),
    "re": ("match", "search", "findall", "sub", "compile", "IGNORECASE", "DOTALL"),
    "sys": ("argv", "exit", "stdout", "stderr"),
    "csv": ("reader", "writer", "DictReader", "DictWriter"),
}

_BUILTIN_NAMES = frozenset(dir(builtins))


@dataclass
class GuardReport:
    """Outcome of a single CodeGuardian.analyze() call."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repaired_code: Optional[str] = None
    needs_llm_fix: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "repaired_code": self.repaired_code,
            "needs_llm_fix": self.needs_llm_fix,
        }


class CodeGuardian:
    """Validates Python code produced by a small model."""

    def analyze(self, code: str) -> GuardReport:
        if not code.strip():
            return GuardReport(False, errors=["Empty code"], needs_llm_fix=False)

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return GuardReport(
                False,
                errors=[f"SyntaxError at line {exc.lineno}: {exc.msg}"],
                needs_llm_fix=True,
            )

        defined = self._collect_defined(tree)
        used = self._collect_used(tree)
        candidates = self._filter_candidates(used, defined)
        missing_libs = self._detect_missing_imports(code, candidates)

        warnings: list[str] = []
        if missing_libs:
            fixed = self._try_autofix(code, missing_libs)
            if fixed is not None:
                try:
                    fixed_tree = ast.parse(fixed)
                except SyntaxError:
                    return GuardReport(
                        False, errors=["Autofix produced invalid syntax"],
                        needs_llm_fix=True,
                    )
                fixed_defined = self._collect_defined(fixed_tree)
                fixed_used = self._collect_used(fixed_tree)
                fixed_candidates = self._filter_candidates(fixed_used, fixed_defined)
                # Remove libs and symbols we just imported — they're now defined.
                fixed_candidates -= set(missing_libs.keys())
                for symbols in missing_libs.values():
                    fixed_candidates -= set(symbols)

                if not fixed_candidates:
                    return GuardReport(
                        True,
                        warnings=[f"Auto-added imports: {missing_libs}"],
                        repaired_code=fixed,
                    )
                return GuardReport(
                    False,
                    errors=[f"Still undefined after auto-import: {sorted(fixed_candidates)}"],
                    warnings=[f"Auto-added imports: {missing_libs}"],
                    repaired_code=fixed,
                    needs_llm_fix=True,
                )

        if candidates:
            return GuardReport(
                False,
                errors=[f"Undefined names: {sorted(candidates)}"],
                warnings=warnings,
                needs_llm_fix=True,
            )

        return GuardReport(True)

    def generate_repair_prompt(self, code: str, report: GuardReport) -> str:
        errs = "\n".join(f"- {e}" for e in report.errors)
        return (
            "The following Python code has errors detected by an analyzer.\n"
            f"Errors:\n{errs}\n\n"
            "Fix ONLY the listed errors. Do not change logic, do not rename "
            "existing functions or variables, do not add new features.\n\n"
            "Code:\n```python\n"
            f"{code}\n"
            "```\n\n"
            "Reply with the fixed code inside a single ```python block."
        )

    # ── helpers ──────────────────────────────────────────────────────

    def _collect_defined(self, tree: ast.AST) -> set[str]:
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(node.name)
            elif isinstance(node, ast.arg):
                out.add(node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                out.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                out.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    out.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Global):
                out.update(node.names)
            elif isinstance(node, ast.Nonlocal):
                out.update(node.names)
        return out

    def _collect_used(self, tree: ast.AST) -> set[str]:
        return {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }

    def _filter_candidates(self, used: set[str], defined: set[str]) -> set[str]:
        return {
            name
            for name in (used - defined - _BUILTIN_NAMES)
            if len(name) > 1 and not name.isupper()
        }

    def _detect_missing_imports(self, code: str, candidates: set[str]) -> dict[str, list[str]]:
        """Returns {lib: [symbols_used]} for libs whose symbols appear unused.

        Example: {"json": ["dumps"], "os": ["getcwd"]}
        """
        missing: dict[str, list[str]] = {}
        for lib, symbols in _AUTOFIX_LIBS.items():
            used_symbols = [s for s in symbols if s in candidates]
            if not used_symbols:
                continue
            # Already imported the module?
            if re.search(rf"^\s*import\s+{re.escape(lib)}\b", code, re.M):
                continue
            # Already imported some of the symbols?
            if re.search(rf"^\s*from\s+{re.escape(lib)}\s+import\b", code, re.M):
                continue
            missing[lib] = used_symbols
        return missing

    def _try_autofix(self, code: str, libs: dict[str, list[str]]) -> Optional[str]:
        """Prepend `import X` + `from X import <used_symbols>` for each lib."""
        if not libs:
            return None
        lines: list[str] = []
        for lib, symbols in libs.items():
            lines.append(f"import {lib}")
            lines.append(f"from {lib} import {', '.join(symbols)}")
        header = "\n".join(lines)
        fixed = f"{header}\n\n{code}"
        try:
            compile(fixed, "<autofix>", "exec")
        except SyntaxError:
            return None
        return fixed
