# Agent Fleet Evidence Audit

**Reviewed revision:** `ff120cabec048665ace013b527600f4cc7844cdd`  
**Review date:** 2026-11-19  
**Purpose:** distinguish inventory, import conformance, offline construction, synthetic invocation, and real task capability. These are separate claims and must never share one "healthy" badge.

## 1. Canonical inventory

The generated `reports/fleet_inventory.json` declares 106 records:

| Framework | Records | What this count means |
|---|---:|---|
| Core | 20 | Built-in `src/agents/AGENT_CLASSES` |
| NovaMind | 79 | Metadata records from `src/novamind/registry/data/nova.yaml` |
| Legacy | 7 | Explicit compatibility/service entries in `src/fleet/inventory.py` |
| **Total** | **106** | Inventory records, not 106 independently proven autonomous workers |

The inventory currently declares eight cross-framework name aliases whose canonical owner is Core: architect, coder, compliance, devops, documentation, performance, refactor, and tester. These are not eight additional independent capabilities.

## 2. What the fleet checks actually prove

- Inventory generation is metadata-only and does not import all agent modules.
- The default conformance check imports each declared module and checks that its declared symbol exists.
- Deep conformance instantiates and runs the 20 Core agents with a silent deterministic backend.
- NovaMind's deep probe attempts offline construction and a bounded invocation against a synthetic input ladder. It is explicitly marked `mode: fake-clock`; it does not use a real LLM, network, production tools, or representative project tasks.
- Some NovaMind modules are deliberately construction-only or excluded from invocation because their entrypoints are blocking or externally managed.
- The published leaderboard's `healthy` count is a conformance status, not proof of end-to-end task competence, quality, or production readiness.

At this revision, the generated inventory reports 106/106 healthy under its import/entrypoint conformance definition. That must not be presented as "106 fully operational agents".

## 3. Historical evidence that must not be conflated

`reports/all-81-agents-test.json` contains a historical run with many NovaMind constructor errors (for example, classes expecting keyword-only/no positional constructor arguments). It is not an exact-head, current CI run and must not be treated as current failure evidence without reproducing it.

It is nevertheless a useful warning: the old broad test harness used an incompatible generic constructor assumption. The supported current evidence is the fleet probe and the exact-head CI jobs, each with their own limited scope. The historical report should be labelled as historical or regenerated with a contract-aware runner before it is used for decisions.

## 4. Training and capability integration

The codebase contains:
- a 20-agent Core manifest;
- an AST-based NovaMind manifest projection that discovers modules without importing them;
- training plans, training executor/orchestrator and evaluation modules;
- skills, memory/learning, certification and genome components.

The training plan itself states that these layers are not all connected to the live API/agent execution path. Presence in the repository is not proof of live integration. In particular, do not claim that all 106 agents are trained, certified, memory-enabled, or operating under one fully integrated lifecycle.

## 5. Required maturity labels

Use these labels in reports and dashboards:

1. **Discovered** — present in canonical inventory.
2. **Importable** — module imports and declared symbol exists.
3. **Constructible** — constructor contract passes in the declared offline harness.
4. **Invocable (synthetic)** — bounded deterministic probe returns successfully.
5. **Task-validated** — passes a representative, versioned task suite with a real configured provider or deterministic domain harness.
6. **Production-qualified** — passes security, reliability, cost, latency, recovery, permission, and human-approval gates in its intended operating environment.

No agent may be labelled above the highest level actually evidenced for that agent. Missing or stale evidence must produce `unknown`, not `healthy`.

## 6. Next closure gate

- [ ] Generate a per-agent matrix containing inventory ID, canonical/alias status, import result, constructor result, invocation result, harness mode, timestamp, tested commit SHA, and evidence references.
- [ ] Make the report distinguish synthetic probe from real-provider task evaluation.
- [ ] Reproduce or retire the historical `all-81-agents-test.json` report.
- [ ] Run representative tasks for a small critical cohort first (architect, analyst, coder, reviewer, tester, security, DevOps, and NovaMind specialists) before scaling evaluation to all records.
- [ ] Connect manifest, RBAC, skills, memory, training/certification and task-evaluation results to the canonical mission execution path.
- [ ] Keep the inventory count separate from the number of task-validated agents.
