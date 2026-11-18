# ADR-0007: NEXUS is the sole runtime; NovaMind is its engineering subsystem

- Status: Accepted for implementation
- Date: 2026-11-18
- Decision owners: NEXUS maintainers

## Context

The repositories were physically consolidated on 2026-10-12: NEXUS CORE is
the parent platform and `src/novamind/` is the NovaMind subsystem. The separate
`tibatechapp-ship-it/novamind-core` repository is archived historical material,
not a second runtime or an independently evolving product.

The archived repository is not an exact mirror of the embedded subsystem.
At the current tree snapshot, 401 source paths overlap: 366 have identical
Git blob hashes and 35 differ; 42 paths exist only in NEXUS and 27 only in the
archived repository. Blindly copying either tree would overwrite later fixes
or restore backups and historical files.

The embedded subsystem still has overlapping metadata registries and
authorization adapters. In particular, permissive fallbacks could grant
access when an authority module was missing, and the Hive compatibility
registry could manufacture arbitrary mock agents with wildcard permissions.

## Decision

1. **One product and runtime:** NEXUS CORE owns lifecycle, goals, orchestration,
   durable execution, project policy, approvals, and final evidence.
2. **One engineering subsystem:** NovaMind owns specialized agent execution,
   code analysis/review, model routing, agent memory, and engineering skills
   under `src/novamind/`. It is not a second top-level organization or runtime.
3. **One metadata authority:** `src/novamind/registry/data/nova.yaml` is the
   authoritative source for canonical agent identity and metadata. The
   `novamind.registry` API is the supported read interface. Historical
   `_registry` imports remain compatibility shims only.
4. **One authorization authority:** `novamind.security.permissions` owns
   role-to-permission decisions. All registry and Hive entrypoints delegate
   to it. Unknown agents and unavailable policy modules are denied.
5. **Compatibility is not authority:** the old v2 registry and Hive adapter
   surfaces may remain temporarily for import compatibility, but must not
   independently authorize, create agents, or override canonical metadata.
6. **No destructive archive operation:** the archived repository remains
   read-only as provenance until all unique files and divergent changes have
   been individually reviewed and either ported with tests or explicitly
   rejected. Do not unarchive, delete, or mirror it wholesale.

## Output acceptance contract

No model or agent response is considered a verified engineering result merely
because it is non-empty or syntactically plausible. A code change is accepted
only after:
- the task and changed-file scope are recorded;
- static/security checks pass;
- targeted tests and the relevant project test suite pass;
- an independent reviewer evaluates the patch and its risks;
- the result is tied to the exact tested commit SHA;
- required human approval is obtained before privileged or production actions.

A failed, skipped, unavailable, or inconclusive required gate is not success.
The system must report uncertainty and evidence instead of claiming a
"guaranteed correct" result.

## Rollout

This ADR establishes the canonical ownership and closes the known permissive
authorization paths. Follow-up work must inventory every direct consumer of
the v2 registry, compare every archived-only/divergent file, migrate consumers
to the canonical API, and add cross-project end-to-end evaluation before
removing compatibility APIs. No mass rewrite or automatic production repair.
