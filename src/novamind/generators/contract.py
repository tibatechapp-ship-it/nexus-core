"""Generator Contract + Registry.

- GeneratedFile / GeneratedPart / VerifyReport
- GeneratorContract (Protocol)
- GeneratorRegistry (singleton) + @register decorator
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, List, Dict, Optional, Type, runtime_checkable


@dataclass
class GeneratedFile:
    path: str
    content: str
    template: Optional[str] = None
    executable: bool = False

    def __post_init__(self):
        # تطبيع المسار: لا \، لا / في البداية
        self.path = self.path.replace("\\", "/").lstrip("/")


@dataclass
class GeneratedPart:
    generator_name: str
    files: List[GeneratedFile] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_file(self, path: str, content: str, template: str = None) -> "GeneratedPart":
        self.files.append(GeneratedFile(path=path, content=content, template=template))
        return self

    def total_bytes(self) -> int:
        return sum(len(f.content.encode("utf-8")) for f in self.files)

    def paths(self) -> List[str]:
        return [f.path for f in self.files]


@dataclass
class VerifyCheck:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "error"  # error | warning


@dataclass
class VerifyReport:
    passed: bool = True
    checks: List[VerifyCheck] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_check(self, name: str, ok: bool, detail: str = "", severity: str = "error"):
        self.checks.append(VerifyCheck(name, ok, detail, severity))
        if not ok:
            if severity == "error":
                self.passed = False
                self.errors.append(f"{name}: {detail}" if detail else name)
            else:
                self.warnings.append(f"{name}: {detail}" if detail else name)

    def merge(self, other: "VerifyReport"):
        self.checks.extend(other.checks)
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.passed:
            self.passed = False


@runtime_checkable
class GeneratorContract(Protocol):
    """كل مولّد يطبّق هذا."""
    name: str

    def can_handle(self, ir) -> bool: ...
    def generate(self, ir, output_dir: Path) -> GeneratedPart: ...
    def verify(self, part: GeneratedPart) -> VerifyReport: ...


# ============================================================
# Registry
# ============================================================

class GeneratorRegistry:
    def __init__(self):
        self._generators: Dict[str, object] = {}

    def register(self, gen) -> None:
        if not isinstance(gen, GeneratorContract):
            raise TypeError(f"{type(gen).__name__} لا يطبّق GeneratorContract")
        if not getattr(gen, "name", None):
            raise ValueError("المولّد بلا اسم (name)")
        if gen.name in self._generators:
            raise ValueError(f"مولّد مسجّل مسبقًا: {gen.name}")
        self._generators[gen.name] = gen

    def get(self, name: str):
        if name not in self._generators:
            raise KeyError(f"مولّد غير مسجّل: {name}")
        return self._generators[name]

    def all(self) -> List:
        return list(self._generators.values())

    def names(self) -> List[str]:
        return list(self._generators.keys())

    def for_ir(self, ir) -> List:
        return [g for g in self._generators.values() if g.can_handle(ir)]

    def clear(self):
        self._generators.clear()

    def __len__(self):
        return len(self._generators)


REGISTRY = GeneratorRegistry()


def register(gen_cls: Type) -> Type:
    """Decorator: @register على class (ينشئ instance ويسجّل)."""
    REGISTRY.register(gen_cls())
    return gen_cls
