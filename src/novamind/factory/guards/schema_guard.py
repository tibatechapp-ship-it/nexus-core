"""Schema Guard — يتحقق من بنية JSON."""
from __future__ import annotations
from typing import Dict, Any, List

from novamind.factory.guards.base import GuardResult


class SchemaGuard:
    name = "schema_guard"

    def __init__(self, required_keys: List[str] = None, optional_keys: List[str] = None):
        self.required_keys = required_keys or []
        self.optional_keys = optional_keys or []

    def check(self, data: Dict[str, Any]) -> GuardResult:
        result = GuardResult(passed=True, guard_name=self.name)

        # المطلوب
        for key in self.required_keys:
            if key not in data:
                result.add_error(f"missing required key: {key}")

        # المفاتيح الزائدة
        if self.optional_keys:
            allowed = set(self.required_keys) | set(self.optional_keys)
            for key in data.keys():
                if key not in allowed:
                    result.add_warning(f"unexpected key: {key}")

        result.details["keys_present"] = list(data.keys())
        return result
