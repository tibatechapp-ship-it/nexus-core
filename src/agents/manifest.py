"""The Agent Manifest — one immutable reference per agent.

This module is **Layer 1** of the agent-training plan: the single record that
ties together an agent's identity, its skills, the gates a task must pass
before it is "done", the adversarial vectors it must survive, and the memory
scope its lessons live in. It is deliberately additive: nothing in the running
framework imports it yet, so the default behaviour is byte-for-byte unchanged.

Two sources feed every manifest, and only these two:

* the **agent class** itself (``name``/``group``/``system_prompt``/``tools``) —
  the single source of identity, so the manifest can never drift;
* the ``_EXTRAS`` table below — the training metadata that has no home on the
  class yet (title, plan spec, skills, gates, adversarial).

The module owns no I/O, no clock and no randomness, so it is hermetic and
cheap to build the whole 20-agent suite on the phone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict

from src.agents import AGENT_CLASSES
from src.agents.base import BaseAgent

__all__ = [
    "AgentManifest",
    "ManifestError",
    "KNOWN_ADVERSARIAL",
    "KNOWN_GATES",
    "KNOWN_SKILLS",
    "KNOWN_TOOLS",
    "MUTATING_TOOLS",
    "all_manifests",
    "build_manifests",
    "get_manifest",
    "manifest_problems",
    "validate_suite",
]

#: Agent ids are lower-case slugs (``architect``, ``security_auditor`` ...).
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: Every tool name the framework knows, executable or declarative.
#: Executable in-framework: ``{read, list, grep}`` (see ``SAFE_TOOL_NAMES``);
#: the rest are declarative capabilities the server holds behind a gate.
KNOWN_TOOLS: frozenset[str] = frozenset(
    {
        # -- executable in-framework --------------------------------------
        "read",
        "list",
        "grep",
        # -- declarative capability vocabulary ----------------------------
        "write",
        "edit",
        "bash",
        "files",
        "search",
        "scan",
        "web",
        "design",
        "math",
        "brainstorm",
        "observe",
        "metrics",
        "alerts",
        "delegate",
        "communicate",
        "deploy",
        "profile",
        "restart",
        "logs",
    }
)

#: Tool names that let an agent change the workspace — a ReAct loop is only
#: worth it for those; a read-only agent answers in a single call.
MUTATING_TOOLS: frozenset[str] = frozenset({"write", "edit", "bash"})

#: Tool names that are executable in-framework (see ``SAFE_TOOL_NAMES``).
EXECUTABLE_TOOLS: frozenset[str] = frozenset({"read", "list", "grep"})

#: Skills a manifest may reference (the 5 seeded defaults of ``src.skills``).
KNOWN_SKILLS: frozenset[str] = frozenset(
    {
        "code-review",
        "security-audit",
        "architecture-review",
        "documentation",
        "testing",
    }
)

#: Verification gates a task must pass before it may be called "done".
KNOWN_GATES: frozenset[str] = frozenset(
    {"ruff", "mypy", "annotations", "pytest", "adversarial", "smoke"}
)

#: Adversarial vectors the framework is expected to survive.
KNOWN_ADVERSARIAL: frozenset[str] = frozenset(
    {
        "prompt_injection",
        "command_injection",
        "sql_injection",
        "path_traversal",
        "xss",
        "template_injection",
        "unicode_injection",
        "null_byte",
        "resource_exhaustion",
        "fuzz_input",
        "role_confusion",
        "byzantine_backend",
        "split_brain",
        "cascading_failure",
    }
)


@dataclass(frozen=True)
class AgentManifest:
    """The immutable record that describes one agent completely.

    ``identity``/``tools`` are copied from the agent class at build time, so
    the class stays the single source of truth and this record stays a
    consistent projection of it.
    """

    #: Lower-case slug, unique — equals the agent class ``name``.
    id: str
    #: Agent group (``core``/``planning``/``quality``/``ops``/``sub``).
    group: str
    #: Human-readable title (the Arabic label the UI shows).
    title: str
    #: Key into the training-plan registry (``coder``, ``security``, ...).
    spec: str
    #: The persona: role, tone, language and refusal lines.
    identity: str
    #: Skills injected *before* execution (subset of :data:`KNOWN_SKILLS`).
    skills: tuple[str, ...]
    #: Allowed tools (must be a subset of :data:`KNOWN_TOOLS`).
    tools: tuple[str, ...]
    #: Verification gates a task must pass before it is "done".
    gates: tuple[str, ...]
    #: Adversarial vectors the agent must survive.
    adversarial: tuple[str, ...]
    #: The scope its learned lessons live in.
    memory_scope: str
    #: Whether the agent mutates the workspace and so needs a ReAct loop.
    tools_required: bool

    def to_dict(self) -> dict[str, object]:
        """A JSON-friendly view (lists, not tuples)."""
        return {
            "id": self.id,
            "group": self.group,
            "title": self.title,
            "spec": self.spec,
            "identity": self.identity,
            "skills": list(self.skills),
            "tools": list(self.tools),
            "gates": list(self.gates),
            "adversarial": list(self.adversarial),
            "memory_scope": self.memory_scope,
            "tools_required": self.tools_required,
        }


class ManifestError(ValueError):
    """Raised when the manifest suite is incomplete or inconsistent."""


class _Extra(TypedDict):
    """The training metadata a manifest carries over the agent class."""

    title: str
    spec: str
    skills: tuple[str, ...]
    gates: tuple[str, ...]
    adversarial: tuple[str, ...]


def _needs_tools(tools: Sequence[str]) -> bool:
    """True when an agent may mutate the workspace and needs a ReAct loop."""
    return any(name in MUTATING_TOOLS for name in tools)


#: Per-agent training metadata (everything the agent class does not carry).
_EXTRAS: dict[str, _Extra] = {
    # -- core -------------------------------------------------------------
    "architect": _Extra(
        title="المهندس المعماري",
        spec="architect",
        skills=("architecture-review",),
        gates=("ruff", "mypy", "pytest"),
        adversarial=("role_confusion", "byzantine_backend"),
    ),
    "coder": _Extra(
        title="المهندس المبرمج",
        spec="coder",
        skills=("code-review", "testing"),
        gates=("ruff", "mypy", "pytest"),
        adversarial=("command_injection", "path_traversal", "null_byte"),
    ),
    "reviewer": _Extra(
        title="المراجع",
        spec="quality",
        skills=("code-review", "architecture-review"),
        gates=("ruff", "mypy", "pytest"),
        adversarial=("prompt_injection", "role_confusion"),
    ),
    "tester": _Extra(
        title="مهندس الاختبارات",
        spec="quality",
        skills=("testing", "code-review"),
        gates=("ruff", "pytest"),
        adversarial=("null_byte", "resource_exhaustion"),
    ),
    "debugger": _Extra(
        title="مهندس التشخيص",
        spec="debugging",
        skills=("code-review", "testing"),
        gates=("ruff", "pytest"),
        adversarial=("byzantine_backend", "cascading_failure"),
    ),
    # -- planning ---------------------------------------------------------
    "planner": _Extra(
        title="المخطِّط",
        spec="planner",
        skills=(),
        gates=("pytest",),
        adversarial=("prompt_injection", "unicode_injection"),
    ),
    "analyst": _Extra(
        title="المحلِّل",
        spec="analyst",
        skills=(),
        gates=("pytest",),
        adversarial=("prompt_injection", "unicode_injection"),
    ),
    "researcher": _Extra(
        title="الباحث",
        spec="researcher",
        skills=("documentation",),
        gates=("pytest",),
        adversarial=("prompt_injection", "unicode_injection"),
    ),
    "designer": _Extra(
        title="المصمِّم",
        spec="designer",
        skills=("documentation",),
        gates=("ruff",),
        adversarial=("xss", "null_byte"),
    ),
    "estimator": _Extra(
        title="المقدِّر",
        spec="estimator",
        skills=(),
        gates=("pytest",),
        adversarial=("unicode_injection",),
    ),
    # -- quality ----------------------------------------------------------
    "security_auditor": _Extra(
        title="المدقق الأمني",
        spec="security",
        skills=("security-audit",),
        gates=("ruff", "pytest", "adversarial"),
        adversarial=(
            "prompt_injection",
            "sql_injection",
            "xss",
            "template_injection",
            "role_confusion",
        ),
    ),
    "performance": _Extra(
        title="مهندس الأداء",
        spec="quality",
        skills=("code-review",),
        gates=("ruff", "pytest"),
        adversarial=("resource_exhaustion",),
    ),
    "documentation": _Extra(
        title="كاتب التوثيق",
        spec="quality",
        skills=("documentation",),
        gates=("ruff", "mypy"),
        adversarial=("xss",),
    ),
    "refactor": _Extra(
        title="مهندس إعادة الهيكلة",
        spec="quality",
        skills=("code-review", "architecture-review"),
        gates=("ruff", "mypy", "pytest"),
        adversarial=("path_traversal", "null_byte"),
    ),
    "compliance": _Extra(
        title="مسؤول الامتثال",
        spec="quality",
        skills=("security-audit",),
        gates=("ruff", "pytest", "adversarial"),
        adversarial=("role_confusion", "sql_injection"),
    ),
    # -- ops --------------------------------------------------------------
    "orchestrator": _Extra(
        title="المنسِّق",
        spec="orchestrator",
        skills=(),
        gates=("pytest", "smoke"),
        adversarial=("split_brain", "cascading_failure", "byzantine_backend"),
    ),
    "devops": _Extra(
        title="مهندس العمليات",
        spec="devops",
        skills=("testing",),
        gates=("pytest", "smoke"),
        adversarial=("resource_exhaustion", "cascading_failure"),
    ),
    "monitor": _Extra(
        title="المراقب",
        spec="monitor",
        skills=(),
        gates=("smoke",),
        adversarial=("resource_exhaustion", "cascading_failure"),
    ),
    "recovery": _Extra(
        title="مهندس التعافي",
        spec="recovery",
        skills=("testing",),
        gates=("pytest", "smoke"),
        adversarial=("cascading_failure", "split_brain"),
    ),
    "reporter": _Extra(
        title="المقرِّر",
        spec="reporter",
        skills=("documentation",),
        gates=("ruff", "mypy"),
        adversarial=("unicode_injection",),
    ),
}


def _duplicates(items: Sequence[str]) -> list[str]:
    """Return the repeated values of ``items``, in first-seen order."""
    seen: set[str] = set()
    dupes: list[str] = []
    for item in items:
        if item in seen and item not in dupes:
            dupes.append(item)
        seen.add(item)
    return dupes


def manifest_problems(manifest: AgentManifest) -> tuple[str, ...]:
    """Return every consistency problem in ``manifest`` (empty = valid).

    Pure and total: it never raises, so callers can aggregate findings.
    """
    problems: list[str] = []
    ident = manifest.id or "<empty>"

    if not _ID_RE.match(manifest.id):
        problems.append(f"{ident}: invalid id (want a lower-case slug)")

    for field in ("title", "spec", "identity", "memory_scope"):
        if not getattr(manifest, field).strip():
            problems.append(f"{ident}: empty {field}")

    unknown_tools = sorted(t for t in manifest.tools if t not in KNOWN_TOOLS)
    if unknown_tools:
        problems.append(f"{ident}: unknown tools {unknown_tools}")
    dup_tools = _duplicates(manifest.tools)
    if dup_tools:
        problems.append(f"{ident}: duplicate tools {dup_tools}")
    if manifest.tools_required and not manifest.tools:
        problems.append(f"{ident}: tools_required but no tools declared")

    unknown_skills = sorted(s for s in manifest.skills if s not in KNOWN_SKILLS)
    if unknown_skills:
        problems.append(f"{ident}: unknown skills {unknown_skills}")
    dup_skills = _duplicates(manifest.skills)
    if dup_skills:
        problems.append(f"{ident}: duplicate skills {dup_skills}")

    if not manifest.gates:
        problems.append(f"{ident}: no gates declared")
    unknown_gates = sorted(g for g in manifest.gates if g not in KNOWN_GATES)
    if unknown_gates:
        problems.append(f"{ident}: unknown gates {unknown_gates}")

    unknown_adversarial = sorted(
        a for a in manifest.adversarial if a not in KNOWN_ADVERSARIAL
    )
    if unknown_adversarial:
        problems.append(f"{ident}: unknown adversarial {unknown_adversarial}")
    dup_adversarial = _duplicates(manifest.adversarial)
    if dup_adversarial:
        problems.append(f"{ident}: duplicate adversarial {dup_adversarial}")

    return tuple(problems)


def build_manifests(
    agents: Iterable[type[BaseAgent]] = AGENT_CLASSES,
) -> dict[str, AgentManifest]:
    """Build one manifest per agent class, or raise :class:`ManifestError`.

    Aggregates *every* finding (missing extra row, orphan row, invalid
    manifest) into a single error so a fix round is one pass, not a ladder.
    """
    agent_list = list(agents)
    errors: list[str] = []
    manifests: dict[str, AgentManifest] = {}

    for cls in agent_list:
        extra = _EXTRAS.get(cls.name)
        if extra is None:
            errors.append(f"{cls.name!r}: no _EXTRAS row")
            continue
        manifest = AgentManifest(
            id=cls.name,
            group=cls.group,
            title=extra["title"],
            spec=extra["spec"],
            identity=cls.system_prompt,
            skills=tuple(extra["skills"]),
            tools=tuple(cls.tools),
            gates=tuple(extra["gates"]),
            adversarial=tuple(extra["adversarial"]),
            memory_scope=f"agent:{cls.name}",
            tools_required=_needs_tools(cls.tools),
        )
        problems = manifest_problems(manifest)
        errors.extend(problems)
        manifests[cls.name] = manifest

    orphan_rows = sorted(set(_EXTRAS) - _declared_ids(agent_list))
    if orphan_rows:
        errors.append(f"orphan _EXTRAS rows: {orphan_rows}")

    if errors:
        raise ManifestError("; ".join(errors))
    return manifests


def _declared_ids(agents: Sequence[type[BaseAgent]]) -> set[str]:
    """The ids an agent list declares."""
    return {cls.name for cls in agents}


def all_manifests() -> dict[str, AgentManifest]:
    """Build and return one manifest per built-in agent (keyed by id)."""
    return build_manifests()


def get_manifest(agent_id: str) -> AgentManifest:
    """Return the manifest for ``agent_id`` (raises ``KeyError`` if absent)."""
    try:
        return all_manifests()[agent_id]
    except KeyError as exc:
        raise KeyError(f"no manifest for agent {agent_id!r}") from exc


def validate_suite(
    agents: Iterable[type[BaseAgent]] = AGENT_CLASSES,
) -> Mapping[str, AgentManifest]:
    """Build the suite for ``agents``, raising on any gap (a P1 gate).

    Guarantees: exactly one manifest per declared agent and none other, and
    every manifest passes :func:`manifest_problems`.
    """
    return build_manifests(list(agents))
