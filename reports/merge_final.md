# Merge Final Report — private → public (2026-10-19)

**Result: PASS.** `~/nexus-core-private` (Day 4 `consensus` + Hyper-Agent 2.0 +
BYOK connectors + exec-sandbox isolation fix) is now in `~/nexus-core` with all
gates green.

## Commits on `feature/novamind-factory` (public)
| Commit | Subject |
| --- | --- |
| `b91259a` | feat(hyper): autonomous loop + BYOK connectors + agent API |
| `ae53995` | test(hyper): hermetic tests for the loop and the BYOK registry |
| `4ca17f9` | feat(learning): add consensus tool + explain_event wire shape (Day 4) |
| `21e6e0e` | docs: refresh README metrics + record Day-1 build and merge reports |
| _(this file)_ | docs(reports): merge final report |

25 files changed, +1931 / -8.

## Push status
| Remote | Branch | SHA |
| --- | --- | --- |
| origin (GitHub) | feature/novamind-factory | `21e6e0e` (+ this report commit) |
| gitlab | feature/novamind-factory | `21e6e0e` (+ this report commit) |
| local | feature/novamind-factory | `21e6e0e` (+ this report commit) |

## Private side
- `~/nexus-core-private` HEAD = `ea00f78` (unchanged; no remotes).
- Untouched foreign WIP there: `agents_review.py`, `agents_review_all.py`,
  `stress_test.py`, `reports/agents_review_all/`.

## Gates (merged public tree)
- lead/import smoke — OK
- `ruff check .` — 1 pre-existing error (`nexus_agent.py:850`, foreign WIP), 0 new
- `check_annotations.py` — OK (167 files)
- `mypy` framework — clean (167); merged hyper files — clean (15)
- `pytest --cov --cov-fail-under=95 --ignore=tests/novamind`
  → **3105 passed, 1 skipped, 99.94%**

## Backups
- Branch `backup_before_merge_20261019_150541` in BOTH repos.
- `~/nexus-backup-20261019_150541.tar.gz` (6.1 MB).

## `main` — not updated
`main` (`075120a`, v1.17.0) had diverged from this branch (3 merge commits), so
a plain push is impossible. Work reaches `main` via **PR #22**:
https://github.com/tibatechapp-ship-it/nexus-core/pull/22

## Next
1. Merge PR #22 (then optionally bump + tag, e.g. `v1.18.0`).
2. Subsequent Day-2 work continues in `~/nexus-core-private`.
