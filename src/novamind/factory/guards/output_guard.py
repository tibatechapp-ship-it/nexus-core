"""Output Guard — يتحقق من مخرجات LLM عامة."""
from __future__ import annotations
from typing import Dict, Any, List

from novamind.factory.guards.base import GuardResult


class OutputGuard:
    name = "output_guard"

    def __init__(
        self,
        min_length: int = 1,
        max_length: int = 1_000_000,
        required_substrings: List[str] = None,
        forbidden_substrings: List[str] = None,
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.required_substrings = required_substrings or []
        self.forbidden_substrings = forbidden_substrings or [
            "TODO: implement",
            "pass  # implement",
            "raise NotImplementedError",
            "placeholder",
            "# ...",
        ]

    def check(self, data: Dict[str, Any]) -> GuardResult:
        result = GuardResult(passed=True, guard_name=self.name)
        output = data.get("output") or data.get("text") or data.get("code") or ""

        if not isinstance(output, str):
            result.add_error(f"output must be string, got {type(output).__name__}")
            return result

        # الطول
        if len(output) < self.min_length:
            result.add_error(f"output too short: {len(output)} < {self.min_length}")

        if len(output) > self.max_length:
            result.add_error(f"output too long: {len(output)} > {self.max_length}")

        # مطلوب
        for sub in self.required_substrings:
            if sub not in output:
                result.add_error(f"missing required: {sub!r}")

        # ممنوع
        for sub in self.forbidden_substrings:
            if sub in output:
                result.add_warning(f"suspicious placeholder: {sub!r}")

        result.details["output_length"] = len(output)
        return result
