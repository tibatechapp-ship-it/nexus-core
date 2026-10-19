# Save + Merge report — 2026-10-18

Scope: commit all uncommitted work in both copies (`~/nexus-core` public,
`~/nexus-core-private` private), push what has remotes, decide the
private→public merge, don't break any test.

## Premise check (done BEFORE acting)

The pasted batch block labelled the pending private work **"Day 2 —
execute_code + ReAct agent loop"**. That label is stale:

- Day 2 is **already committed in BOTH repos** — `react_agent.py` exists in
  `~/nexus-core/src/learning/` *and* `~/nexus-core-private/src/learning/`.
- The real uncommitted private work was **Hyper-Agent 2.0, Day 1** (BYOK
  subsystem: loop + connectors + API), which had been left uncommitted awaiting
  review.

So the plan's "merge Day 2 private→public" step had nothing to merge. The
actual work was committed under an accurate message instead.

## Public repo — `~/nexus-core`

Branch `feature/novamind-factory`, both remotes `origin` (GitHub) + `gitlab`.

| commit | subject | files |
|---|---|---|
| `6726e24` | `fix(learning): isolate exec_sandbox import to its top-level module` | `src/learning/tools.py`, `tests/conftest.py`, `tests/test_learning_tools.py`, `tests/adversarial/test_security.py` |
| `3f3c6f6` | `docs(learning): record Phase-2 Day-3 collab + exec-sandbox isolation fix` | `CHANGELOG.md`, `AGENTS.md` |

- **Pushed** to origin + gitlab: `7ef148e..3f3c6f6`. Remote head = `3f3c6f6`.
- Gate: **3048 passed, 1 skipped, 100.00% coverage**; mypy 167 clean;
  annotations 167 clean.
- `ruff check .` is red **only** on Foreign WIP `nexus_agent.py:850` (E402) —
  pre-existing, left untouched per the isolation rule.

## Private repo — `~/nexus-core-private`

Branch `master`, **NO remotes** → local commit only.

| commit | subject |
|---|---|
| `411797d` | `feat(hyper): Hyper-Agent 2.0 autonomous loop + BYOK connectors + API` |
| `446029e` | `test(hyper): hermetic tests for the loop and the BYOK registry` |
| `2a634dd` | `docs(hyper): README Hyper-Agent section + Day-1 build report` |

- Gate: **3105 passed, 1 skipped, 99.94% coverage** (floor 95).
- Pre-commit fix: added the two missing annotations the gate never caught
  (`connectors/base.py` `__init__ -> None`, `connectors/registry.py`
  `list_providers -> list[str]`) — the repo's `check_annotations.py` scope is
  `src`/CLI only, so the hyper files were outside it.
- Left untracked on purpose (Foreign WIP): `agents_review.py`,
  `agents_review_all.py`, `reports/agents_review_all/`, `stress_test.py`.

## Merge decision — NOT performed (flagged for tyba)

The private copy is the **Day-4+ dev sandbox** (deliberately no remotes). The
two things private holds that public does not:

1. Day-4 `consensus` tool (`ec16ce7`, private-only commit)
2. Hyper-Agent 2.0 Day 1 (the three commits above)

Promoting either to public is a separate decision that needs its own feature
branch + full public gates + PR on the public repo (SCOPE rules). Not merged
here — awaiting tyba's go.

Repos have **unrelated histories** (private was a fresh `git init`), so any
future promotion is a `git cherry-pick <hash>` / file copy, never a `git merge`.

## Integrity

- No test broken: public 3048 / private 3105, both green.
- No Foreign WIP touched in either repo.
- Public + gitlab in sync; private is local-only by design.
