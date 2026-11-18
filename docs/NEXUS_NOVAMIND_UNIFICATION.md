# NEXUS + NovaMind: unified runtime contract

NEXUS CORE is the single platform and runtime. NovaMind is the software
engineering subsystem embedded under `src/novamind/`. The archived
`novamind-core` repository is a historical source, not a second running
system.

See [ADR-0007](adr/ADR-0007-nexus-novamind-single-runtime.md) for the binding
ownership, authority, safety, and output-acceptance decisions.

## Ownership

| Concern | Canonical owner |
| --- | --- |
| Product/runtime lifecycle, goals, projects, durable orchestration, approvals | NEXUS CORE |
| Agent identity and metadata | `novamind.registry.data.nova.yaml` |
| Agent authorization | `novamind.security.permissions` |
| Agent execution and engineering specialization | `src/novamind/` |
| Cross-project engineering workflow and evidence | NEXUS coding engine + durable workflow |
| Historical provenance | Archived `novamind-core` repository; read-only |

## Runtime boundaries

- Import NovaMind through `novamind.*` from the NEXUS distribution.
- `novamind.registry` is the supported metadata API.
- `novamind._registry` and Hive registry adapters are compatibility surfaces,
  not independent data stores.
- The old v2 registry is retained only while its direct consumers are audited
  and migrated. It must not become a fallback authority.
- RBAC is evaluated by `novamind.security.permissions`; failure to load the
  policy, or an unknown agent identity, denies access.
- No agent may be fabricated with wildcard permissions when lookup fails.

## Why we are not copying the archived repository over NEXUS

A content-hash comparison found 401 overlapping NovaMind source paths:
366 identical and 35 divergent; there are also 42 NEXUS-only and 27
archive-only paths. Some archive-only paths are backups, broken copies, or
historical UI files. Therefore a wholesale overwrite is unsafe and would
reintroduce stale or broken code. Every divergence needs a reviewed migration
decision.

## Verified-output policy

A response from a model is a proposal, not proof. An engineering result is
accepted only when its patch, static/security evidence, targeted and project
tests, independent review, and exact tested commit SHA are recorded. Required
gate failures or skips remain visible as non-success. Human approval is
required for privileged actions and production changes.

## Current consolidation scope

Implemented in this change:
- route registry permission checks through the canonical RBAC policy;
- remove permissive authorization fallbacks;
- resolve Hive agents from canonical registry metadata instead of creating
  arbitrary wildcard mock agents;
- derive default RBAC roles from canonical registry categories, with unknown
  identities denied;
- make missing canonical metadata an explicit error rather than silently
  falling back to the legacy v2 registry.

Remaining migration work:
- inventory all direct imports of the legacy v2 and Hive registries;
- migrate consumers and convert compatibility layers to projections;
- compare and port any valuable archive-only or divergent implementation
  individually;
- run real end-to-end engineering tasks across the user's project portfolio.
