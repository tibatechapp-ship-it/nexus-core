# Genome unification (P3) — ADR

**Status:** accepted · **Date:** 2026-10-29 · **Branch:** `feat/p3-genome-unification`
**Supersedes:** the two-store arrangement shipped before P3 (v1 SQLite + v2 JSON).

## Context

Two genomes lived side by side and both claimed to be the truth:

| Store | Type | Written by | Read by |
| --- | --- | --- | --- |
| v1 `Genome(SessionStore)` | SQLite table `agent_genome` in `sessions.db` | `Council` (`outcome_from_influence`), `/api/genome*`, `nexus_agent.get_genome()` | `/api/genome*`, `orchestrator/router.py` (`fitness_of`) |
| v2 `GenomeV2` | JSON (`data/genome.json`, `$NEXUS_GENOME_PATH`) | `/api/training/*`, task outcomes, `_record_council_judgements` | Academy UI, `training/engine.py`, `/api/maintenance/metrics` |

The symptom: one council session updated *two* stores with *different* numbers, and
the Academy — which reads v2 — could show an agent that had just debated with a
flat 0.5 fitness, because the judgement landed in SQLite.

## Decision

**`GenomeV2` is the single source of truth.** The legacy API survives as an
adapter over it.

```
             ┌──────────────────────────── src ────────────────────────────┐
Council ───► │ Genome ──► GenomeV2Adapter ──► GenomeV2 ──► genome_store    │──► data/genome.json
orchestrator │   │                                                          │
/api/genome  │   └──(SessionStore passed)──► legacy SQLite  [back-compat]  │
             └──────────────────────────────────────────────────────────────┘
```

1. `Genome(store)` inspects its argument. A `GenomeV2` (or anything exposing the
   v2 surface) switches it into **adapter mode** (`is_genome_v2 == True`);
   anything else keeps the original SQLite code path, byte-for-byte.
2. Adapter mode is a *translation*, not a second store: the v1 shapes
   (`rank`, `detail`, `record`, `outcome_from_influence`, `export`, …) are
   projected from v2 rows. `fitness_of` keeps its `0.5` neutral default so the
   router contract is unchanged.
3. The launcher builds `get_genome()` on `get_genome_v2()` and seeds it with
   `COUNCIL_MEMBERS` (six members), so a fresh install shows a full council in
   the Academy. `PATCH /api/genome/{id}` now edits that same store.
4. `Council` skips its injected `judge` when the genome it was handed already
   *is* v2 (`is_genome_v2`): one session = one write, never two counts of the
   same judgement.

## Migration

`src/novamind/genome_migrate.py` folds pre-P3 history into the v2 store **once**,
during `_install_genome_layer()`:

* only when the v2 JSON does not exist yet (`migrate_if_fresh`) — an existing
  canonical store is never re-imported;
* additive only: `max()` of counters, v1 `standing` anchors the task EWMA, and
  fitness/status are rebuilt from the merged fields;
* never fatal: a missing, old or corrupt SQLite file simply imports nothing.

The legacy table itself is left untouched — it is the rollback path.

## NovaMind → manifest bridge

`src/agents/novamind_manifest.py` projects the 60+ modules of
`src/novamind/agents/` into `AgentManifest` records:

* discovery is pure `ast` (no module is imported — those files have import-time
  side effects and a phone cannot pay for them);
* `CORE` maps the modules that have a real training plan to their spec
  (`db_migration → database`, `k8s → devops`, …); the rest get `default`;
* skills come from the framework's **closed vocabulary** (`KNOWN_SKILLS`), so
  every record passes `manifest_problems()` — no drifting tags;
* the framework's 20 manifests always win on id collisions;
* `training/engine._manifest()` consults the bridge only when the framework
  lookup missed, and `/api/training/agents?roster=1` unions trained agents +
  genome members + the bridge. The default (roster off) keeps the pre-P3
  contract of "trained agents only".

## Acceptance criteria and where they are proven

| Criterion | Proof |
| --- | --- |
| One council session → one store | `tests/test_genome_unification.py::test_council_session_writes_to_the_v2_store_only` (legacy table empty, judge not called) |
| Academy shows the six council members | `::test_academy_roster_shows_the_six_council_members` (`/agents?roster=1`, `/fitness`) |
| Legacy behaviour untouched | `::test_legacy_genome_is_still_the_legacy_genome`, `::test_adapter_and_legacy_share_the_rank_shape` |
| Migration safe | `::test_migration_is_additive_and_idempotent`, `::test_migration_never_raises_on_broken_input` |
| NovaMind modules are described | `::test_bridge_manifests_are_valid_and_never_shadow_the_framework`, `::test_training_engine_uses_the_bridged_spec` |

## Rollback

Revert the branch. The SQLite genome was never dropped, never written by P3, and
still contains every pre-P3 row, so the old readers resume exactly where they
stopped. `data/genome.json` can be deleted to re-import from SQLite.
