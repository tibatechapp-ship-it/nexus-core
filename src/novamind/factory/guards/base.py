"""Guard Base — Protocol لكل Guards."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, List, Optional, Dict, Any, runtime_checkable


@dataclass
class GuardResult:
    """نتيجة فحص واحد."""
    passed: bool
    guard_name: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


@runtime_checkable
class Guard(Protocol):
    """كل guard يجب أن يطبّق هذا."""
    name: str

    def check(self, data: Dict[str, Any]) -> GuardResult:
        """يتحقق من البيانات. يرجع GuardResult."""
        ...
