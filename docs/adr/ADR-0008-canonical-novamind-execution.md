# ADR-0008: One Canonical NovaMind Execution and Pipeline Layer

- Status: Proposed (implementation in review)
- Date: 2026-11-18
- Supersedes: none
- Related: ADR-0007

## Context

NEXUS contains two copies of the NovaMind factory executor and two copies of
the factory pipeline implementation. The implementations had drifted in imports,
authorization wiring, result metadata, and small data-handling details. Maintaining
parallel implementations makes security fixes and behavior changes difficult to
prove consistently.

## Decision

1. `novamind.factory.executor` is the sole implementation of agent execution.
2. `novamind.factory.pipeline` is the sole implementation of factory pipeline
   definitions, context handling, stage execution, summaries, and formatting.
3. Historical `novamind.core.hive.factory.executor` and
   `novamind.core.hive.factory.pipeline` paths remain compatibility facades.
4. The executor facade delegates execution to the canonical executor. Its legacy
   provider symbols remain patchable for callers that historically injected
   providers through the hive module.
5. The pipeline facade re-exports canonical objects and functions; the pipeline
   registry is the same object, not a copy.
6. No caller may treat a compatibility facade as a separate policy or runtime.
   Authorization remains governed by the canonical RBAC authority in
   `novamind.security.permissions`.

## Compatibility and migration

- Preserve historical import paths and exported names.
- Keep `run_factory` as an alias of `run_pipeline`.
- Keep `execute_agent`, `execute_agent_sync`, prompt parsing, and router
  helpers available through the hive facade.
- New code should import from `novamind.factory`.
- Do not delete the facade modules until repository-wide import and runtime
  evidence demonstrates that no supported consumer needs them.

## Validation

The implementation is guarded by tests that assert the hive pipeline exports
are object-identical to canonical exports, and that hive executor calls delegate
to the canonical executor while retaining legacy provider injection behavior.
Full CI on the exact pull-request head is required before merge.
