# Merge Audit — private → public (2026-10-19)

## Goal
Bring `~/nexus-core-private` (Day 4 `consensus` + Hyper-Agent 2.0 + BYOK
connectors + the exec-sandbox isolation fix) into the public repo
`~/nexus-core`, on branch `feature/novamind-factory`, with all gates green.

## Backups (Phase 1)
- Branch `backup_before_merge_20261019_150541` created in BOTH repos.
- Archive `~/nexus-backup-20261019_150541.tar.gz` (6.1 MB, 3084 entries;
  excludes `.git`, `node_modules`, `__pycache__`, caches).

## Merge set (Phase 2) — 12 items, private → public
New directories:
- `connectors/` (9 modules: base + openai/anthropic/groq/ollama/deepseek/gemini + registry)
- `hyper_app/` (routers/agent.py, services/llm_factory.py, `__init__`s)

New files:
- `hyper_agent.py` (455 lines)
- `tests/test_hyper_agent.py` (34 tests)
- `tests/test_byok_integration.py` (8 tests)
- `reports/day1_bugfixes.md`, `reports/save_and_merge.md`

Updated files (verified SUPSET — private carries all public content):
- `src/learning/tools.py`   (5 → 6 tools; adds `consensus`, `explain_event`)
- `src/learning/__init__.py` (exports `consensus`)
- `tests/test_learning_tools.py` (0 public-only lines; +232 private-only)
- `tools_config.json`       (adds the `consensus` config block)
- `README.md`               (stale metrics 1848@98.9% → 3105@99%, mypy 103→167)

Superset check: `requirements.txt` and `pyproject.toml` are byte-identical
(no new dependency needed). The only "public-only" lines in the updated
files are stale values being replaced (count words, old metrics, an import
line extended with `Iterable`) — no functionality lost.

## Deliberately EXCLUDED
- Foreign WIP: `agents_review.py`, `agents_review_all.py`, `stress_test.py`,
  `reports/agents_review_all/` — belong to another session; untouched.
- Runtime/generated: `data/*.db`, `data/hyper_agent.jsonl`,
  `hive/data/self_eval.db`, `logs/*.lock`, `memory/security_log.jsonl`,
  `security_audit_report.json`, `.*_cache` — gitignored, never staged.
- `reports/` bulk copy skipped (public already holds its own report files).

## Gates (Phase 3) — on the merged public tree
| Gate | Result |
| --- | --- |
| import smoke (`hyper_agent`, `connectors`, `hyper_app`, `consensus`) | OK |
| `ruff check .` | 1 error — **pre-existing**, `nexus_agent.py:850` E402 (foreign `/simple.html` WIP, already in HEAD). 0 new. |
| `scripts/check_annotations.py` | OK — 167 files |
| `mypy zyvo-telegram.py zyvo-voice.py src` | Success — 167 files |
| `mypy hyper_agent.py connectors hyper_app` | Success — 15 files |
| `pytest --cov --cov-fail-under=95 --ignore=tests/novamind` | **3105 passed, 1 skipped, 99.94%** (1 skip = ed25519 unavailable) |

Post-merge numbers equal the private baseline (3105 / 99.94%) →
the merge is behaviour-preserving.

## Verdict
PASS. Public repo now contains Day 4 + Hyper-Agent 2.0 (+BYOK) with all
gates green; no foreign WIP, no runtime artefacts, nothing lost.
