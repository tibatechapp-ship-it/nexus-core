"""Manifest projection for the NovaMind agent modules (P3 bridge).

``src/agents/manifest.py`` describes the framework's 20 agents — the ones the
launcher runs directly.  ``src/novamind/agents/*.py`` holds a much larger
second library (analyzer, refactor, sql, react, k8s, ...) that the training
engine can already *teach* but could not *describe*: no manifest ⇒ no ``spec``
⇒ no curriculum beyond ``default``.

This module closes that gap **without importing a single novamind agent**:

* discovery is pure ``ast`` — the 70+ modules have import-time side effects and
  a phone cannot afford to import them just to read a class name;
* the framework's 20 manifests always win on an id collision (``architect``,
  ``coder``, ``analyzer`` ... exist in both worlds and the framework's row is
  the one already wired into the launcher);
* nothing here runs at import time of the framework — the training engine
  calls :func:`get_novamind_manifest` only when its own lookup missed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.agents.manifest import AgentManifest, all_manifests

__all__ = [
    "NovamindModule",
    "CORE",
    "discover",
    "get_novamind_manifest",
    "novamind_manifests",
    "training_manifests",
]

#: Where the NovaMind agent library lives, relative to the repo root.
_AGENTS_DIR = Path(__file__).resolve().parents[1] / "novamind" / "agents"

#: Curated training metadata for the core NovaMind modules — the ones the
#: training plan actually has a curriculum for.  ``spec`` picks the plan (the
#: real curriculum); ``skills`` may only use the framework's closed vocabulary
#: (:data:`src.agents.manifest.KNOWN_SKILLS`) so every record stays valid.
CORE: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    # id -> (spec, skills)
    "coder": ("coder", ("code-writing",)),
    "architect": ("architect", ("architecture-review",)),
    "chief_architect": ("architect", ("architecture-review",)),
    "architecture": ("architect", ("architecture-review",)),
    "api_design": ("architect", ("architecture-review",)),
    "analyzer": ("analyzer", ("code-review",)),
    "multilang_analyzer": ("analyzer", ("code-review",)),
    "arabic_analyzer": ("analyzer", ("code-review",)),
    "code_review": ("review", ("code-review",)),
    "quality": ("review", ("code-review",)),
    "security": ("security", ("security-audit",)),
    "sec_eng": ("security", ("security-audit",)),
    "secrets": ("security", ("security-audit",)),
    "privacy": ("security", ("security-audit",)),
    "compliance": ("security", ("security-audit",)),
    "auth": ("security", ("security-audit",)),
    "crypto": ("security", ("security-audit",)),
    "injection": ("security", ("security-audit",)),
    "xss": ("security", ("security-audit",)),
    "dependency": ("security", ("security-audit",)),
    "tester": ("testing", ("testing",)),
    "test_runner": ("testing", ("testing",)),
    "test_generator": ("testing", ("testing",)),
    "qa_devops": ("testing", ("testing",)),
    "refactor": ("refactor", ("code-review",)),
    "deadcode": ("refactor", ("code-review",)),
    "duplication": ("refactor", ("code-review",)),
    "complexity": ("performance", ("code-review",)),
    "performance": ("performance", ("code-review",)),
    "documentation": ("documentation", ("documentation",)),
    "techwriter": ("documentation", ("documentation",)),
    "db_migration": ("database", ("code-review",)),
    "sql": ("database", ("code-review",)),
    "orm": ("database", ("code-review",)),
    "transaction": ("database", ("code-review",)),
    "docker": ("devops", ("testing",)),
    "k8s": ("devops", ("testing",)),
    "terraform": ("devops", ("testing",)),
    "nginx": ("devops", ("testing",)),
    "cicd": ("devops", ("testing",)),
    "devops_eng": ("devops", ("testing",)),
    "monitoring": ("monitor", ("testing",)),
    "git_agent": ("default", ("code-review",)),
    "react": ("default", ("code-review",)),
    "vue": ("default", ("code-review",)),
    "css": ("default", ("code-review",)),
    "a11y": ("default", ("code-review",)),
    "rtl": ("default", ("code-review",)),
    "pm": ("default", ("architecture-review",)),
    "researcher": ("default", ("documentation",)),
    "junior_eng": ("default", ("code-review",)),
    "senior_eng": ("default", ("architecture-review",)),
}

#: Capability keywords → the framework's five known skills (first match wins).
_CAPABILITY_SKILLS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("secret", "privacy", "compliance", "sec", "threat", "auth", "crypto",
      "injection", "xss", "audit", "vuln"), "security-audit"),
    (("doc", "write", "readme", "explain"), "documentation"),
    (("test", "qa", "verify", "assert"), "testing"),
    (("architect", "design", "plan", "spec", "schema", "api"), "architecture-review"),
)

@dataclass(frozen=True)
class NovamindModule:
    """One discovered NovaMind agent module (static facts only)."""

    id: str
    path: str
    description: str
    capabilities: Tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "description": self.description,
            "capabilities": list(self.capabilities),
        }


def _literal(node: ast.AST) -> Optional[object]:
    """``ast`` literal value, or ``None`` when the node is computed."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _scan(tree: ast.AST) -> Tuple[str, str, Tuple[str, ...]]:
    """(name, description, capabilities) from a parsed agent module."""
    name = ""
    description = ""
    capabilities: Tuple[str, ...] = ()
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        for target in targets:
            key = (
                target.id if isinstance(target, ast.Name)
                else target.attr if isinstance(target, ast.Attribute)
                else None
            )
            if key is None:
                continue
            literal = _literal(value)
            if key.lower() == "name" and not name and isinstance(literal, str):
                if len(literal) < 40:
                    name = literal
            elif key in ("DESCRIPTION", "description") and not description:
                if isinstance(literal, str):
                    description = literal
            elif key == "CAPABILITIES" and not capabilities:
                if isinstance(literal, (list, tuple)):
                    capabilities = tuple(
                        str(c) for c in literal if isinstance(c, str)
                    )
    return name, description, capabilities


def discover(directory: Optional[Path] = None) -> Dict[str, NovamindModule]:
    """Every NovaMind agent module that declares an id (never imports one)."""
    base = Path(directory) if directory is not None else _AGENTS_DIR
    found: Dict[str, NovamindModule] = {}
    try:
        paths = sorted(base.glob("*.py"))
    except OSError:  # pragma: no cover - a missing library is not an error
        return found
    for path in paths:
        if path.name.startswith("_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, SyntaxError):  # pragma: no cover - defensive
            continue
        name, description, capabilities = _scan(tree)
        if not name or not name.isidentifier():
            continue
        found.setdefault(
            name.lower(),
            NovamindModule(
                id=name.lower(),
                path=f"src/novamind/agents/{path.name}",
                description=description,
                capabilities=capabilities,
            ),
        )
    return found


def _skills_for(module_id: str, capabilities: Tuple[str, ...]) -> Tuple[str, ...]:
    """Curated skills first, then one derived from the module's capabilities."""
    curated = CORE.get(module_id)
    if curated is not None:
        return curated[1] or ("code-review",)
    joined = " ".join(capabilities).lower()
    for words, skill in _CAPABILITY_SKILLS:
        if any(word in joined for word in words):
            return (skill,)
    return ("code-review",)


def _manifest(module: NovamindModule, *,
              framework: Dict[str, AgentManifest]) -> AgentManifest:
    spec = CORE.get(module.id, ("default", ()))[0]
    group = framework.get(module.id)
    identity = module.description or f"NovaMind module {module.id}"
    return AgentManifest(
        id=module.id,
        group=group.group if group is not None else "novamind",
        title=(module.description or module.id).splitlines()[0][:80],
        spec=spec,
        identity=identity,
        skills=_skills_for(module.id, module.capabilities),
        tools=(),
        gates=("pytest",),
        adversarial=(),
        memory_scope=f"novamind:{module.id}",
        tools_required=False,
    )


def novamind_manifests(directory: Optional[Path] = None) -> Dict[str, AgentManifest]:
    """Manifests for the NovaMind library (framework ids are skipped)."""
    framework = all_manifests()
    out: Dict[str, AgentManifest] = {}
    for agent_id, module in discover(directory).items():
        if agent_id in framework:
            continue
        out[agent_id] = _manifest(module, framework=framework)
    return out


def get_novamind_manifest(agent_id: str) -> Optional[AgentManifest]:
    """The NovaMind manifest for ``agent_id`` (``None`` when unknown)."""
    key = str(agent_id or "").strip().lower()
    if not key:
        return None
    return novamind_manifests().get(key)


def training_manifests(directory: Optional[Path] = None) -> Dict[str, AgentManifest]:
    """The whole trainable roster: framework manifests plus NovaMind modules."""
    merged: Dict[str, AgentManifest] = dict(all_manifests())
    merged.update(novamind_manifests(directory))
    return merged
