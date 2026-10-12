"""Guard Chain — يشغّل عدة guards متتالية."""
from __future__ import annotations
from typing import List, Dict, Any, Optional

from novamind.factory.guards.base import Guard, GuardResult


class GuardChain:
    def __init__(self, guards: List[Guard] = None):
        self.guards: List[Guard] = guards or []

    def add(self, guard: Guard) -> "GuardChain":
        self.guards.append(guard)
        return self

    def check(self, data: Dict[str, Any], stop_on_error: bool = False) -> GuardResult:
        """يشغّل كل guards. يرجع نتيجة مُدمجة."""
        combined = GuardResult(passed=True, guard_name="chain")

        for guard in self.guards:
            try:
                r = guard.check(data)
            except Exception as e:
                r = GuardResult(passed=False, guard_name=guard.name)
                r.add_error(f"{type(e).__name__}: {e}")

            combined.errors.extend(f"[{r.guard_name}] {e}" for e in r.errors)
            combined.warnings.extend(f"[{r.guard_name}] {w}" for w in r.warnings)

            if not r.passed and stop_on_error:
                combined.passed = False
                return combined

            if not r.passed:
                combined.passed = False

        return combined


def build_default_chain() -> GuardChain:
    """Chain جاهز للاستخدام العام."""
    from novamind.factory.guards.code_guard import CodeGuard
    from novamind.factory.guards.import_guard import ImportGuard
    from novamind.factory.guards.output_guard import OutputGuard
    from novamind.factory.guards.hallucination_guard import HallucinationGuard
    return GuardChain([
        CodeGuard(),
        ImportGuard(),
        OutputGuard(),
        HallucinationGuard(),
    ])
