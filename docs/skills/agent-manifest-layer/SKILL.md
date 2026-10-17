---
name: agent-manifest-layer
description: Add a validated, single-source "manifest" layer over an existing multi-agent codebase (each agent class already carries name/group/prompt/tools) WITHOUT changing any runtime behaviour — the manifest becomes the reference for identity, skills, gates, adversarial vectors and memory scope, with strict vocabulary validation and full negative tests. Use when asked to unify/formalize agent metadata, add "AgentManifest", or build the identity layer before wiring training/skills/UI.
---

# Agent Manifest Layer

Turn scattered per-agent metadata into ONE immutable record per agent, derived
from the agent class so it can never drift, plus a small fixed vocabulary for
everything the class does not carry. Read-only: nothing imports it yet.

## When to use
- A multi-agent repo where each agent class already declares
  `name/group/description/system_prompt/tools/permissions`.
- The user wants a "single reference" / manifest / identity layer before
  wiring skills, training, gates or a UI panel.
- You must NOT change runtime behaviour (default path byte-for-byte identical).

## Design (the shape that works)
1. **One module**, e.g. `src/agents/manifest.py` — not 20 files (one source,
   one test target, reviewable diff).
2. **Frozen dataclass** `AgentManifest` with:
   `id, group, title, spec, identity, skills, tools, gates, adversarial,
   memory_scope, tools_required` (all `tuple[str, ...]` for the list fields).
   Add `to_dict()` returning lists for JSON/APIs.
3. **Derive the driftable half from the class** — `id=cls.name`,
   `group=cls.group`, `identity=cls.system_prompt`, `tools=tuple(cls.tools)`.
   NEVER re-type identity/tools into the data table; that is where drift lives.
4. **`_EXTRAS` table** (one `TypedDict` row per agent id) carries only the
   non-derivable half: `title, spec, skills, gates, adversarial`.
   Derive `memory_scope=f"agent:{id}"` and
   `tools_required = any(t in MUTATING_TOOLS for t in tools)`.
5. **Vocabulary constants** (frozensets): `KNOWN_TOOLS`, `KNOWN_SKILLS`,
   `KNOWN_GATES`, `KNOWN_ADVERSARIAL`. Do NOT invent names — mine the real
   ones from the code (`SAFE_TOOL_NAMES`, skill loader's seeds, the gates the
   repo actually runs, the adversarial test filenames/categories).
6. **Aggregating validator** `manifest_problems(m) -> tuple[str, ...]`
   (pure, total, never raises) + `ManifestError` raised by
   `build_manifests()` with ALL findings joined — one fix pass, not a ladder.
   Checks: slug id, non-empty text fields, each tool/skill/gate/adversarial in
   its vocabulary, duplicates, `gates` non-empty, `tools_required ⇒ tools`.
7. **Suite guards**: `build_manifests(agents)` errors on a **missing row** and
   on an **orphan row** (a `_EXTRAS` key with no class). `validate_suite`
   delegates to `build_manifests` — do not add a second unreachable guard.
8. **Do not touch `__init__.py`** in P1 — importing the manifest into the
   package `__init__` while it imports `AGENT_CLASSES` creates a cycle. Callers
   use `from src.agents.manifest import ...`. Wire it in the next phase.

## Tests (the two criteria)
- Happy: `len(all_manifests()) == len(AGENT_CLASSES)`; every manifest
  `manifest_problems(m) == ()`; class projection holds
  (`m.identity == cls.system_prompt`, `m.tools == tuple(cls.tools)`);
  frozenset membership; `to_dict()` is `json.dumps`-able; frozen raises.
- Negative (parametrized): bad id, each empty field, unknown tool/skill/gate/
  adversarial, duplicate tool/skill/adversarial, empty gates,
  `tools_required` with no tools, a subclass with no `_EXTRAS` row
  (`match="no _EXTRAS row"`), a truncated agent list (`match="orphan"`).
  Build bad records by `dataclasses.replace(all_manifests()["coder"], ...)`.

## Coverage discipline
- Write negatives to cover every `manifest_problems` branch.
- If a guard is provably unreachable (e.g. a redundant set-equality check
  after `build_manifests` already enforces it), **delete it** — a dead branch
  is the one line that breaks a 100% gate.
- If a test needs an optional dep, guard it (`importorskip` / capability
  probe) so closing a coverage gap never re-opens a red CI.

## Verify
```bash
pytest tests/test_agent_manifest.py -q
python -m pytest tests/test_agent_manifest.py -q --cov=src.agents.manifest \
  --cov-report=term-missing      # dotted module form; the FILE path form does not work
ruff check src/agents/manifest.py tests/test_agent_manifest.py
mypy src/agents/manifest.py
python scripts/check_annotations.py
# then the repo's real gate, e.g.
python -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind
```

## Pitfalls
- Re-typing `tools`/`system_prompt` into the data table ⇒ drift; always derive.
- `--cov=src/agents/manifest.py` (path) silently reports 0%; use
  `--cov=src.agents.manifest` or a directory.
- Wrong vocabulary names (e.g. a tool never declared) make 20/20 fail on the
  first run — mine the real names first.
- Do not export from `src/agents/__init__.py` while the module imports
  `AGENT_CLASSES` from it (import cycle at package import).
