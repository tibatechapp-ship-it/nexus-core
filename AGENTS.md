# nexus-core — project memory

Unified AI Agent System: **Memory + Learning + Security + 20 Agents** — the
merge of tyb-zyv-ai (stdlib-only 20-agent framework + TUI) and novamind-core
(server-side orchestration). v1.0.0 → v1.30.0, MIT, repo
github.com/tibatechapp-ship-it/nexus-core. Decision 2026-10-12 by tyba:
merge everything, lose NO feature, test after each stage.

## Layout (two layers, one repo)
- Framework (stdlib-only, phone-safe): src/{agents,core,patterns,memory,learning,
  security,tools,tui} + zyvo-telegram.py + zyvo-voice.py + tests/ (1218 @ 99%).
- Novamind layer (optional `novamind` extras): src/novamind/* + tests/novamind/*
  + scripts/novamind/ + legacy root scripts (github_client.py, groq_pool.py,
  unified_agent.py, security.py, tools.py, user.py, ... — some are IMPORTED by
  src/novamind, do NOT move/delete them). Infra: Makefile, docker-compose.yml,
  deploy/, Dockerfile.backend, .sh ops scripts stay at root.
- Runtime junk (novamind's data/, audit jsons, .nova_memory.jsonl, bundles,
  .bak*/.BROKEN) was EXCLUDED — re-add only real features.

## Verify before shipping (must all pass)
```bash
ruff check .
mypy zyvo-telegram.py zyvo-voice.py src
python scripts/check_annotations.py        # every function type-annotated
python -m pytest --cov                     # 1218 tests @ 99%, floor 95%
```
- ruff/mypy/check_annotations scope = the framework surface ONLY
  (src/novamind + tests/novamind + scripts/novamind + legacy root scripts are
  excluded/ignored — they keep their own lint legacy; coverage too
  [tool.coverage.run] omits src/novamind/*).
- tests/novamind auto-skip when fastapi absent (importorskip in
  tests/novamind/conftest.py) so the plain `pytest --cov` gate stays green on
  the phone. CI installs `.[dev,novamind]` and runs the real novamind suite:
  unit+observability = gate (their own historical scope), full suite =
  non-blocking report. CI needs data/company/*.json + sqlite dbs + ZAI_API_KEY_1/
  GROQ_API_KEY_1 test envs (see .github/workflows/test.yml).
- Novamind full suite was NEVER a hard gate even in their repo (continue-on-error
  there too). Do not silently graduate it.

## Architecture (framework key files)
- src/core: types, backend.py (LLMBackend + EchoBackend offline), model_router,
  context_manager (token accounting, compaction, offload), resilience (CommandQueue
  + retry), watchdog, zyvo_client, streaming (StreamingBackend/StreamChunk,
  shoulda: plain backend → ONE chunk).
- src/agents: base, sub_agent (tools ⊆ parent, max_depth), registry, state,
  metrics, communication + 20 built-in agents; `all_agents(backend)` factory.
- src/patterns: supervisor, pipeline (`checkpoints=`+`run_id=` resumable),
  fanout, delegation, blackboard, checkpoint (CheckpointStore JSON-persistable).
- src/memory: 4 SQLite stores + manager (remember/recall/forget, retention/
  compress/summaries). DB: $ZYVO_MEMORY_DB else ~/.local/share/tyb-zyv-ai/.
- src/learning: collector (Experience), lesson extractor/store (Jaccard dedup),
  orchestrator, ContinualLearningManager (schedule policy), AntiForgetting
  (protect/conflict/consolidate). DB via src.memory.base.connect.
- src/security: 8 regex agents + orchestrator + classifier + reporter + CLI
  `python -m src.security PATH [--json] [--fail-on LEVEL]` (default high).
- src/tools: schemas + executor (parse_tool_calls, LocalToolExecutor read-only
  tools confined to root, run_with_tools ReAct loop). ToolPolicy wires tools
  into patterns (src/patterns/_stage.py run_stage; Supervisor/Pipeline/Fanout/
  Delegation take optional `tools=` — None = old behaviour byte-for-byte).
- src/tui: ZyvoTUI (Textual); TuiState auto-registers 20 agents; ToolRunsScreen
  ctrl+t/:tools; LessonsScreen ctrl+l/:lessons; security export →
  ~/.local/share/..., never the working tree.
- src/novamind: see docs/novamind/ARCHITECTURE.md (their own docs).

## Decisions
- 2026-10-12: unified as nexus-core v1.0.0 (merge, coexistence layout). Both old
  repos archived after release. Framework keeps its 99% gate; novamind layer
  gated at its own historical scope (unit+observability).
- 2026-10-12: novamind deps → optional `novamind` extras in pyproject; phone
  stays stdlib-only (pip install of fastapi/pydantic/cryptography aborted by
  user — CI verifies novamind instead).
- 2026-10-12: Phase-11 files (streaming.py, checkpoint.py, toolruns.py + 2 test
  files) were UNCOMMITTED in tyb-zyv-ai — copied from the working tree here.
- Version lives in `pyproject.toml` ONLY; `src.__version__` reads it live
  (tomllib) — never hard-code a literal (a regression the version guard catches).
  `docs/openapi.yaml` `info.version` and a `## vX.Y.Z` CHANGELOG heading must
  match it too, and `scripts/check_version_sync.py` guards tag↔pyproject↔openapi.
- Coverage badge: shields endpoint at .github/badges/coverage.json, committed
  by the badge CI job (framework coverage only).
- Adversarial suite: 92 vectors / 8 categories, HELD = pass. Stdlib-only
  invariants in tests/adversarial scan FRAMEWORK_FILES (novamind excluded by
  design). Do NOT widen to src/novamind.
- 2026-10-12: Council lives in `src/novamind/council` (excluded from framework
  gates) but its tests (`tests/test_council.py`) are stdlib-only so they run on
  the phone gate too — pure helpers + the offline-simulation path, never a live
  provider.
- 2026-10-12: Council offline-fallback is FAILURE-DRIVEN (a live error flips a
  process-wide 60s offline window), NOT a pre-flight probe. A probe on slow-but-
  live `zai_glm` calls (15–48s) misclassified them as dead and forced offline.

## Lessons
- `git ls-files` only copies TRACKED files — new uncommitted work (Phase 11) was
  nearly lost in the merge. When mirroring a repo, also copy `git status` output.
- novamind's repo tracks runtime junk (data/, audit jsons, bundles) — never copy
  those into a fresh project; runtime state belongs in .gitignore.
- pytest importorskip in a per-dir conftest = elegant deps-gated collection skip.
- pytest-cov does NOT enforce [tool.coverage.report] fail_under on its own —
  pass --cov-fail-under explicitly in CI.
- One root conftest only; no second conftest in tests sub-dirs without
  __init__.py (shadowing).
- v1.5 chat UI rename bug: `save()` persists the *current* conversation, not the
  target — to persist an arbitrary conversation use `saveConv(c)`. (The rename
  flow originally called `save()` and silently updated the wrong conv.)
- v1.5 headless-CDP gotcha: a synthetic `blur()` is a no-op (the element is not
  truly focused in headless), so an onblur-commit never runs and tests lie —
  commit on `keydown`/Enter directly. Real browsers do fire the blur.
- v1.5 perf note: with dead ZAI keys a chat takes ~22s (5 providers × 7 retries
  before the MockProvider fallback). Provider retry/budget control is a v2.0
  (offline / provider-admin) target.
- `unified_agent.py` (legacy root server) was BROKEN post-merge: `from core.*`
  imports (16 refs) but no top-level `core/` — novamind's modules live at
  `src/novamind/core/`. FIXED 2026-10-12 (option 1): added
  `sys.path.insert(0, ROOT/"src")` + all `core.*` → `novamind.core.*`.
  Verified: `python3 -c "import unified_agent"` → OUTPUT "OK — NovaMind
  Unified 10.0.0". NOTE: with no keys → MockProvider fallback; needs `.env`
  at ROOT (dotenv IS installed) or NOVAMIND_HOME/.env. `_load_from_env`
  defaults NOVAMIND_HOME to `/public`. Env vars: GEMINI_API_KEY(0-20),
  GROQ_API_KEY_1..20, ZAI_API_KEY_1..4, OPENROUTER_API_KEY_1..5,
  MISTRAL_API_KEY_1..9, OLLAMA_HOST. NO plain GROQ_API_KEY.

## Release flow
1. Verify gates → commit + push main
2. `gh release create v1.0.0 --title "nexus-core v1.0.0 — Unified AI Agent System" --notes "..."`
3. Archive old repos: `gh repo archive tibatechapp-ship-it/novamind-core` +
  `gh repo archive tibatechapp-ship-it/tyb-zyv-ai` (after both have a README
  pointer to nexus-core).

## Archive (docs/legacy/)
- `docs/legacy/AGENTS_HISTORY.md` — the older session/release notes (v1.5 →
  v1.22, one-off audits, the merge era) split out of this file on 2026-10-20 to
  keep the root memory focused. Grep it for historical detail.
- `docs/legacy/` also holds recovered historical files (commit e528b54):
  unified_agent_v10.py (970 lines, LangGraph/LSP/MCP/A2A),
  unified_ui_v0.html (49KB ar UI), registry_v3.1_arabic.py
  (`git show bcce802:src/novamind/core/hive/factory/registry.py.old`),
  + README. Rule: never delete a file without saving it in git first.

## Sessions note
- Full session notes: vault `04 Sessions/2026-10-12 nexus-core merge*.md`.

## 2026-10-20 — v1.29.0 release (bounded logs + leak guard + maintenance metrics)

- Branch `feature/v1.29.0` (3 commits: `30df162` feat(security) rotation ·
  `77befed` test(conftest) leak guard · `20f0b37` feat(maintenance) metrics API).
  **PR #36 squash-merged → `main` = `5fbe578`** on local + origin + gitlab.
- Release commit **`a5dc348`** `chore(release): v1.29.0` — 4 lockstep files
  (pyproject 1.27.0→1.29.0, docs/openapi.yaml, CHANGELOG, SCOPE). Annotated tag
  **`v1.29.0`** (object `b0a2808`) at `a5dc348`, self-consistent
  (`git show v1.29.0:pyproject.toml` → 1.29.0), on BOTH remotes.
  `git rev-parse main origin/main gitlab/main v1.29.0^{}` = all `a5dc348`.
- **GitHub Release v1.29.0 (Latest)** = not draft, not prerelease.
- **VERSION-CHAIN GAP REPAIRED**: v1.28.0/v1.28.1 had remote tags but pyproject
  stuck at 1.27.0 (never bumped) → CHANGELOG entries for v1.28.0 (#34
  `3eca05c`) + v1.28.1 (#35 `9f7d41a`) backfilled with VERIFIED facts, then
  lockstep bumped to 1.29.0.
- WHAT SHIPPED:
  · `src/novamind/core/security_gatekeeper.py`: log rotation
    (`DEFAULT_LOG_MAX_BYTES=10*1024*1024`, `DEFAULT_LOG_BACKUPS=5`, env
    `NEXUS_SECURITY_LOG_MAX_BYTES`/`NEXUS_SECURITY_LOG_BACKUPS`,
    `_rotate_if_needed()` before append; `backup_count<=0` → unlink).
    `tests/novamind/security/test_gatekeeper_rotation.py` (8).
  · `tests/conftest.py`: autouse `_guard_no_runtime_leaks` (fails a test that
    writes runtime state into `memory/`) + `pytest_configure` points the security
    log at `tempfile.gettempdir()/"_pytest_security.jsonl"`.
  · `src/maintenance/api.py` (NEW): `GET /api/maintenance/metrics`
    (genome 8-key stats + `by_priority{low,medium,high}`) +
    `GET /api/maintenance/tasks` (generate_tasks, ok:false on failure);
    `register(app)` = `app.router.routes.extend` (deferred-router fix); mounted
    in `unified_agent.py` (`MAINTENANCE_OK`). 100% coverage.
- **GATES**: ruff clean · mypy **183** · annotations **183** · real gate
  `pytest --cov --cov-fail-under=95 --ignore=tests/novamind` = **3416 passed,
  1 skipped @ 99.78%** (was 3396; README mypy count 180→183).
- **CONSTRAINT HELD**: did NOT add maintenance paths to `docs/openapi.yaml` —
  the drift guard `test_spec_paths_match_app_both_ways` scans the workbench
  `main.py` only (no maintenance routes) → adding them = phantom-route failure.
  `memory/` clean; `logs/` holds only gitignored service logs + lock files.
- Bundle: `~/backups/nexus-core/nexus-core-v1.29.0.bundle` (2.8M, `--all`).
- **NEXT (v1.30)**: the maintenance metrics `by_priority` breakdown is a
  placeholder (`# TODO(v1.30)`) — wire real priority counts from the genome.

## 2026-10-20 — v1.30.0 release (real priority ledger; read endpoints pure)

- Branch `feature/v1.30-task-log` → **PR #37 squash-merged → `main` =
  `594595f`** on local + origin + gitlab. Commits: `7ab6f9b` feat(maintenance)
  (task_log NEW + api + task_generator + scripts/generate_tasks + conftest +
  tests) · `594595f` `chore(release): v1.30.0` (README + pyproject + openapi +
  CHANGELOG + SCOPE). Annotated tag **`v1.30.0`** at `594595f`, self-consistent
  (`git show v1.30.0:pyproject.toml` → 1.30.0), pushed to BOTH.
  **GitHub Release v1.30.0 (Latest)**.
- WHAT SHIPPED:
  · `src/maintenance/task_log.py` (NEW, stdlib-only, leaf): append-only JSONL
    ledger. `record(*, priority, agent_id="", outcome="generated", reason=None,
    version=None)` never raises; `aggregate(*, window_days=7, log=None)` returns
    BOTH a `window` and an `all_time` view + `is_sample_sufficient`
    (`total_all_time >= NEXUS_MIN_SAMPLE`, default 30). Priority constants
    `LOW="low"`/`MED="medium"`/`HIGH="high"` (lowercase, English — i18n is a UI
    concern). Rotation 10 MiB × 5. Path `$NEXUS_TASK_LOG` → `<repo>/data/
    task_log.jsonl` → tempdir.
  · `# TODO(v1.30)` CLOSED: `/api/maintenance/metrics` now serves REAL
    `by_priority` counts (was a placeholder) + `by_priority_all_time`.
- **DOUBLE-RECORD DEFECT FIXED** (found while proving): `generate_tasks()` used
  to write the ledger at generation time AND `scripts/generate_tasks.py` wrote it
  again after execution → `--apply --max 2` inflated `low` (GET polluted state).
  FIX = planner is now PURE (no `from . import task_log` / no `record`); the
  ledger is written ONLY by `scripts/generate_tasks.py` after a real execute.
  Regression: `test_generate_tasks_does_not_write_ledger` +
  `test_tasks_route_does_not_write_ledger`.
- **LESSON (recorded)**: *read endpoints must be pure* — a GET may not change
  state. Test = call the GET twice and assert state before == after.
- **CONSTRAINT HELD** (unchanged): `/api/maintenance/*` stay OUT of
  `docs/openapi.yaml` — the drift guard scans `main.py` only → adding them =
  phantom-route CI failure. They are documented in `docs/api.md` instead.
- **GATES**: ruff · mypy/annotations **184** · gate recorded **3442 passed,
  1 skipped @ 99.69%**; `test_task_log + test_maintenance` = 54 passed;
  `test_version_sync + test_openapi` = 14 passed. README updated
  (3445 tests, 99.69%, 184 files).
- **LIVE** (service :8000, pid 17577 after `sv restart nexus-core`):
  `/api/health` = 1.30.0; `/api/maintenance/metrics` → `by_priority
  {low:2,medium:0,high:0}`, `all_time` same, `tasks{sample_sufficient:false}` —
  real numbers, not a placeholder. CI `39429745139` SUCCESS · Tests
  `39429745134` SUCCESS.
- **FACT (accepted, not a bug)**: HIGH = 0 is EXPECTED — `task_generator` never
  auto-generates HIGH tasks (a deliberate safety decision). `high_pct` is not a
  contract field; derive it as `by_priority.high / tasks.total_all_time`.
- **REMOVED FROM SCOPE (tyba, verified)**: no v1.30.1. Two claimed bugs were
  artifacts of a browser screenshot (machine-translated keys) — the live HTTP
  contract has lowercase English keys and never had a missing `high_pct`.
  *Never diagnose API behaviour from a browser screenshot; read the contract
  with `curl`.*

## 2026-10-29 — P1 deploy layer (branch `feat/p1-deploy`, NOT pushed)

- Deploy artifacts: `Dockerfile` (multi-stage, uid 10001, HEALTHCHECK
  /api/health, CMD `uvicorn main:app`), `.dockerignore` (`.env` excluded),
  `requirements-docker.txt` (runtime set — the repo installs flat, never `-e .`),
  `docker-compose.yml` (app + postgres:17-alpine + redis:7-alpine + `backup`
  behind `profiles:["backup"]`; app `read_only`, `cap_drop: ALL`, tmpfs /tmp,
  `depends_on: service_healthy`), `scripts/backup_db.sh` + `.cron`,
  `.github/workflows/deploy.yml` (hadolint → compose config → build → boot →
  /api/ready in DRIVER mode → postgres-restart probe → verified backup dump).
- `src/readiness.py` (NEW, stdlib-only): `/api/ready` checks. TCP connect first,
  then psycopg `SELECT 1` / redis `PING` when importable; `mode: driver|tcp`
  says what was ATTEMPTED, `ok`/`error` carry the verdict; NEVER raises.
  `_optional_import()` uses `__import__` so tests can block drivers via
  `builtins.__import__` and still exercise both paths. 100% lines+branches.
- `/api/health` now also returns `service` + `uptime_seconds` (liveness stays
  dependency-free — that split is the whole point).
- compose wires DISCRETE `POSTGRES_*`/`REDIS_*`, never `DATABASE_URL`/
  `REDIS_URL`: `@`/`#` in a password silently corrupts a URL and readiness
  PREFERS the URL → a bad password would poison the probe instead of failing
  loudly. `tests/test_deploy.py` enforces no-URL + full env parity.
- Scripts: `scripts/backup.sh` is the OLD Termux job (git bundle + ~/.nexus
  data) and stays untouched; `scripts/backup_db.sh` is the Postgres one (POSIX
  sh, verify with `gzip -t`, mkdir-lock → exit 3 on overlap, retention).
- Gate notes: `pytest tests/test_ready.py tests/test_deploy.py
  tests/test_openapi.py tests/test_env_docs.py tests/test_version_sync.py
  tests/test_build_api.py` = 52 passed; `ruff check .` clean (2 pre-existing
  F401 in tests/test_openrouter_pool.py removed); compose-spec jsonschema VALID.
- LESSON: `--cov=src/readiness` reports "module was never imported" because the
  tests import through package paths — use `--cov=src` and grep the file.
