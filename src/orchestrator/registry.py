"""Agent registry — loads skills_registry.json and validates vs manifest."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "skills_registry.json"


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    domain: str
    scope: tuple
    not_scope: tuple
    input_schema: dict
    output_schema: dict


class AgentRegistry:
    def __init__(self, path=None, *, manifests=None):
        self.path = path or _REGISTRY_PATH
        self._specs = {}
        self._by_domain = {}
        self._load(manifests)

    def _load(self, manifests):
        if not self.path.exists():
            raise RegistryError(f"registry not found: {self.path}")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RegistryError(f"invalid JSON: {e}")
        specs_raw = raw.get("agents") or {}
        if not isinstance(specs_raw, dict):
            raise RegistryError("registry.agents must be a dict")
        for name, spec in specs_raw.items():
            required = ("domain", "scope", "input_schema", "output_schema")
            if not all(k in spec for k in required):
                raise RegistryError(f"agent {name!r} missing fields")
            self._specs[name] = AgentSpec(
                name=name, domain=spec["domain"],
                scope=tuple(spec["scope"]),
                not_scope=tuple(spec.get("not_scope") or ()),
                input_schema=spec["input_schema"],
                output_schema=spec["output_schema"])
            self._by_domain.setdefault(spec["domain"], []).append(name)
        if manifests is not None:
            missing = set(manifests) - set(self._specs)
            extra = set(self._specs) - set(manifests)
            if missing:
                raise RegistryError(f"missing from registry: {sorted(missing)}")
            if extra:
                raise RegistryError(f"not in manifest: {sorted(extra)}")

    def get(self, name):
        if name not in self._specs:
            raise KeyError(f"agent not registered: {name!r}")
        return self._specs[name]

    def in_domain(self, domain):
        return list(self._by_domain.get(domain, ()))

    def all(self):
        return list(self._specs.values())

    def __len__(self):
        return len(self._specs)


_default = None


def get_registry():
    global _default
    if _default is None:
        try:
            from src.agents.manifest import all_manifests
            _default = AgentRegistry(manifests=all_manifests())
        except Exception:
            _default = AgentRegistry()
    return _default
