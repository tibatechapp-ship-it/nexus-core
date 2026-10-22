# Nexus-Core Changelog

All notable changes to this project. Newest first.

## v1.41.11 — 2026-10-22 — deps: SpeechRecognition 3.10 → 3.17

### Changed
- **`SpeechRecognition>=3.17.0`** (was `>=3.10.0`) in the `voice` extra and
  `requirements.txt`. The only consumer is `zyvo-telegram.py` (STT path),
  and that import is already inside `try/except` with an empty-string
  fallback, so the voice extra stays optional and failure-safe.

Dependabot PR #44. Merged directly (two-line version bump, no code
touched). No test change.

### Verified
- `make check`: all gates green, 3626 passed, cov 99%+.

## v1.41.10 — 2026-10-22 — deps: opentelemetry-sdk 1.20 → 1.45.1

### Changed
- **`opentelemetry-sdk>=1.45.1`** (was `>=1.20`) in the `observability`
  extra. All OpenTelemetry imports in this repo live in
  `src/novamind/observability/` behind `try/except ImportError`, so the
  extra remains optional. `opentelemetry-api>=1.20` and
  `opentelemetry-exporter-otlp-proto-grpc>=1.20` are unchanged; pip's
  resolver will pull a compatible api 1.45+ alongside the new sdk.

Dependabot PR #40. Merged directly (single-line pyproject change, no code
touched). No test change.

### Verified
- `make check`: all gates green, 3626 passed, cov 99%+.

## v1.41.9 — 2026-10-22 — deps: sqlalchemy 2.1.4 → 2.1.5

### Changed
- **`sqlalchemy>=2.1.5`** (was `>=2.1.4`) in the `novamind` extra. Patch-level
  bump: two ORM regression fixes (session-wide expire on multi-row UPDATE;
  `exclude_properties` deprecation warning) and a ForeignKeyConstraint copy
  fix. No API changes, no deprecations affecting this repo's usage.

Dependabot PR #43. Merged directly onto main (single-line pyproject change,
no code touched). No test change.

### Verified
- `make check`: all gates green, 3626 passed, cov 99%+.

## v1.41.8 — 2026-10-22 — OllamaBackend: timeout 180s + retry-once

### Changed
- **`OllamaBackend` timeout raised from 120s to 180s.** In a live 20-agent
  sweep on the phone, `coder` failed at exactly 120.1s — the wall-clock limit
  was hit, not an error. The local 1.7B model occasionally needs more than two
  minutes for a long reply; 180s covers that without changing the fast path.

### Added
- **One retry on transient failure** in `OllamaBackend.generate` — on
  `URLError`, `TimeoutError`, or `OSError`. Waits 2s, then calls once more.
  Non-retryable errors (bad request, model not found) are **not** retried:
  a second call would fail identically.
- **`_build_prompt()` static method** — shared between `generate` and `stream`
  (was duplicated).
- **3 retry tests** in `tests/test_ollama_backend.py`.

### Verified
- `make check`: all gates green, 3626 passed (was 3623), cov 99%+.

No behaviour change on the success path. Backwards compatible.

## v1.41.7 — 2026-10-22 — make check runs version-check; L27

### Changed
- **`make check` now fails on tag/version drift.** Added a `version-check`
  target that runs `scripts/check_version_sync.py`, and appended it to the
  `check` chain (after `sync-version`, before `cov`). Previously this check
  ran only in CI's lint job, which is why the orphan-release error shipped
  twice in one session (v1.41.1→v1.40.0, v1.41.5→v1.41.4). Both would have
  been caught by a local `make check` in seconds.

### Docs
- **L27** — every check that runs in CI must have a Makefile target that
  runs it locally, and `make check` must chain that target. `sync_version.py`
  (writes) and `check_version_sync.py` (reads and gates) are separate targets
  by design.

### Verified
- `make version-check`: `All versions aligned` (pyproject=src=openapi=tag=1.41.6).
- `make check`: all gates green (lint, type, annotations, sync-version,
  version-check, cov 99%+).

No code or test change.

## v1.41.6 — 2026-10-22 — version bookkeeping for v1.41.5

### Fixed
- **`pyproject.toml` / `docs/openapi.yaml` now report `1.41.6`.** The v1.41.5
  tag (`4ec67d8`) was published without bumping `pyproject.toml`, so CI's
  `check_version_sync.py` rejected the orphan release
  (`git tag 1.41.5 > pyproject 1.41.4`). The v1.41.5 code fix (coverage-badge
  gate + fail_under 98) is unchanged; only version bookkeeping is corrected.

### Note
This is the second time in this session the same mistake happened (see L25).
The `make check` local target does not run `scripts/check_version_sync.py`;
only the CI lint job does. Adding it to `make check` would have caught both.

### Verified
- CI on v1.41.5: `Tests` job — SUCCESS (the actual goal of v1.41.5);
  only version-sync failed, fixed here.
- `python scripts/check_version_sync.py`: all four sources agree (locally,
  once tagged).

No code or test change since v1.41.5.

## v1.41.4 — 2026-10-22 — version bookkeeping + L25/L26

### Fixed
- **`pyproject.toml` / `docs/openapi.yaml` now report `1.41.4`.** The three
  tags v1.41.1, v1.41.2 and v1.41.3 were published without bumping
  `pyproject.toml`; CI's `check_version_sync.py` correctly rejected the
  resulting orphan release (`git tag 1.41.3 > pyproject 1.41.0`). This
  release restores the invariant.

### Docs
- **L25** — `make type` must list exactly the files CI type-checks.
  `nexus_agent.py` was only ever type-checked on CI, which is why the
  `list(COUNCIL_MEMBERS)` type error survived until v1.41.3.
- **L26** — any test that imports `nexus_agent` (or `main.py`) must
  `pytest.importorskip("sse_starlette")` first, because CI installs only
  `dev` + `tui`, not the `novamind` extra.

### Verified
- `python scripts/check_version_sync.py`: all four sources agree.
- `make check`: 3604 passed locally.

No production code change since v1.41.3.

## v1.41.0 — 2026-10-22 — Streaming replies via OllamaBackend

### Added
- **`OllamaBackend.stream()`** — incremental reply generation against Ollama's
  `/api/generate` with `"stream": true`. Reads NDJSON line-by-line and yields
  each `response` field as it arrives. Satisfies
  `src.core.streaming.StreamingBackend`, so `iter_stream()` and
  `BaseAgent.stream()` use it automatically. Non-streaming callers still get
  the single `generate()` chunk (backward compatible).
- **`tests/test_ollama_stream.py`** — 10 unit tests (mocked `urlopen`,
  zero network). Covers piece ordering, `done` short-circuit, empty-line and
  empty-response skipping, payload construction, network-error wrapping,
  dict/str/Message input, protocol detection, and `iter_stream()` preference.

### Measured
- Live run against `sam860/qwen3:1.7b-Q4_K_XL` on Termux:
  **340 pieces**, **time-to-first-token 0.60 s**, **total 45.87 s**.
  Before this release the user waited the full 45 s for any output; now the
  first token arrives in 0.6 s (~98.7% reduction in perceived latency).

### Version bookkeeping
- `pyproject.toml` advanced from `1.40.0` to `1.41.0`. The previous doc-only
  tags `v1.40.1`, `v1.40.2`, `v1.40.3` never bumped `pyproject.toml`; that
  drift is corrected here (see entries below).
- `LESSONS.md` extended with L24 (measure streaming by time-to-first-token,
  not by piece count).

### Verified
- `make check`: lint ✅, type (188 files) ✅, annotations ✅,
  cov 99.09% — **3603 passed, 1 skipped**.

## v1.40.3 — 2026-10-22 — LESSONS L23 (release backfill & Latest badge)

### Docs
- **L23** added: after creating releases retroactively for older tags, GitHub
  marks the *last published* release as `Latest`, not the highest semver.
  Re-apply `gh release edit <version> --latest` and verify with
  `gh release list`.

Doc-only tag. No code change. `pyproject.toml` was not bumped.

## v1.40.2 — 2026-10-22 — LESSONS.md consolidation (L1-L22)

### Docs
- **Backfilled L9-L16** — cited in `CHANGELOG.md` but absent from the repo.
- **Added L17-L18** (make-check runtime, `/tmp` read-only on Termux).
- **Migrated 4 lessons** from the now-deleted `docs/LESSONS.md` as L19-L22.
- Removed `docs/LESSONS.md` (stale, different format, fully subsumed).

Doc-only tag. No code change. `pyproject.toml` was not bumped.

## v1.40.1 — 2026-10-22 — OllamaBackend.generate annotations + Message fix

### Fixed
- **`OllamaBackend.generate`** — full type hints added
  (`messages: Sequence[Message]`, `model: str | None`, `-> str`). Unblocks
  `scripts/check_annotations.py`.
- **`Message` dataclass handling** — protocol callers now receive correct
  `role: content` prompts instead of `str(Message(...))`. Backward compatible
  with `dict` and `str` inputs.

### Docs
- **`CHANGELOG.md`** backfilled for v1.40.0, v1.39.0, v1.38.1.

### Verified
- `make check`: lint ✅, type (188 files) ✅, annotations ✅,
  cov 99.09% (3593 passed).


## v1.40.0 — 2026-10-22 — Ollama backend

### Added
- **`OllamaBackend`** (`src/core/backend.py`) — HTTP client for a local Ollama
  instance at `127.0.0.1:11434`, implementing the `LLMBackend` protocol.
  All 20 agents now run through Ollama with `sam860/qwen3:1.7b-Q4_K_XL`.
- **`Message` handling in `OllamaBackend.generate`** — accepts `Message`
  dataclasses, plain dicts, and strings, in that order.

### Changed
- **ZYVO deprecated.** The ZYVO (opencode fork) backend is no longer the
  primary LLM path. The `zyvo.bin` binary was deleted without backup and
  cannot be recovered (see `LESSONS.md` L9). OpenCode official ships as a
  Web UI only, not a REST API (L10). Ollama's HTTP API is the sanctioned
  replacement.
- **`make check` now passes end to end** — `scripts/check_annotations.py`
  flagged `OllamaBackend.generate` as missing type hints. Fixed by adding
  `messages: Sequence[Message]`, `model: str | None = None`, and `-> str`.

### Verified
- `make check`: lint OK, type (188 files) OK, annotations (188 files) OK,
  cov 99.09% (3592 passed).
- 20/20 agents operational via `OllamaBackend`.

## v1.38.1 — 2026-10-22 — `/health` fix + regression test

### Fixed
- **`GET /health` regression** — the endpoint introduced in v1.38.0 was not
  stable across imports. Fixed and covered by a regression test.

### Verified
- `make check`: all gates green.

## v1.39.0 — 2026-10-22 — Root reorganization

### Changed
- **Repository root reorganized** to reduce clutter and make the tree
  navigable on a phone (Termux). No runtime behavior change.

## v1.38.0 — 2026-10-21 — API health, CI hardening, and Quick Start

### Added
- **`GET /health`** — standard health check endpoint for monitoring.
- **Quick Start section** in `README.md` to onboard new users in 3 steps.

### Changed
- **GitHub Actions CI** — `mypy` now type-checks `nexus_agent.py` explicitly.

### Verified
- `make check`: all gates green.

## v1.37.1 — 2026-10-21 — lint hotfix + honest BUG-9 guard

### Fixed
- **Ruff lint regressions in v1.37.0** — `make check` failed with 32 errors
  (E401, E701, E741, F401, F841) in `src/llm/request_log.py` and the three
  new test files. All resolved; behavior is unchanged.
- **`tests/test_bug_9_filenames_consistent.py`** — commit `8e3a969` (shipped
  in v1.37.0) contained `assert len(...) == 0 or True`, which always passes
  and guards nothing. Rewritten with two real assertions: no
  `hyper-agent*.py` shadow, and canonical `hyper_agent.py` exists. Also
  removed the unused `underscore_files` binding and the redundant `**/`
  glob.
- **`test_aggregate_counts`** — corrected the expected count from
  `{"HIGH": 3, "MED": 3, "LOW": 1}` to `{"HIGH": 3, "MED": 4, "LOW": 1}`
  (the test was wrong, the code was right).

### Verified
- `make check`: 3598 passed, 1 skipped, 99.24% coverage, all gates green.

## v1.37.0 — 2026-10-21 — request_log + metrics endpoint

### Added
- **`src/llm/request_log.py`** — append-only JSONL ledger for LLM/orchestrator
  traffic. `record(priority, agent_id, outcome, reason)` never raises;
  `aggregate(window_days=7)` returns honest totals, per-priority counts,
  failure/high percentages, and a `sample_sufficient` flag (>= 100 requests).
  Rotation at 10 MiB with 5 backups (mirrors `task_log.py`). Env override
  via `NEXUS_REQUEST_LOG` + `NEXUS_REQUEST_LOG_MAX_BYTES` for tests.
- **`GET /api/orchestrator/metrics?window_days=7`** — read-only aggregate
  of `/api/orchestrator/execute` traffic, sourced from `request_log.aggregate`.
  Registered in `_ORCHESTRATOR_ROUTES` to survive the catch-all Mount reorder.

### Changed
- **`/api/orchestrator/execute`** now writes one `request_log` entry per
  request via `_record_orchestrator_metric`. The existing `_metrics.record`
  (dashboard + maintenance consumers) is preserved unchanged — recording
  is additive, not a replacement. `priority` is read from the request body
  (defaults to `MED`) and passed through to the new log; `agent_id` comes
  from `subtasks[0].agent`, `outcome` from `result["ok"]`, `reason` from
  `result["error"]` on failure.

### Tests
- 7 hermetic tests for `request_log` (tmp_path + env monkeypatch, rotation
  via `NEXUS_REQUEST_LOG_MAX_BYTES=200`).
- 2 wiring tests for `/api/orchestrator/execute` (FakeOrch, no live Ollama).
- 2 endpoint tests for `GET /api/orchestrator/metrics` (env-mocked log).

### Inherited
All v1.36.0 fixes retained (BUG-1..9, structured outputs, sandbox).

## v1.36.0 — 2026-10-21 — Hyper-Agent BUG audit

### Verified already resolved (no code changes needed)
- **BUG-1**: prune_history_fast replaces history (pure, no duplicate)
- **BUG-2**: ollama num_predict=4000 (was 500)
- **BUG-3**: detect_stall after 3 identical non-terminal actions
- **BUG-4**: stored history drops raw_result
- **BUG-5**: last_parse_error feedback + schema-constrained decoding
- **BUG-6**: sandbox preexec_fn + RLIMIT_CPU/FSIZE/NPROC
- **BUG-7**: sys.executable instead of bare python3
- **BUG-8**: verify_goal gates DONE
- **BUG-9**: README uses hyphen (no underscore drift)

All 9 BUGs from the 2026-10-18 report are resolved. `hyper_agent.py`
was built clean (no legacy to patch — see header for per-BUG evidence).

### Inherited
All v1.33.0 / v1.34.0 / v1.35.0 fixes retained.

## v1.35.0 — 2026-10-21 — structured outputs + BUG-5 fix

### Added
- **`src/llm/structured.py`** — schema-constrained JSON generation via
  Ollama's native `format` parameter. JSON parse errors impossible.
  (`ea9c667`)

### Fixed
- **BUG-5** — `hyper_agent` retry loop on malformed JSON. Now uses
  `HYPER_AGENT_SCHEMA` (enum action + additionalProperties=false) so
  the model cannot invent invalid fields. Falls back to original path
  for non-local providers. (`c1d8940`)

### Tests
- 4 hermetic unit tests for `structured.py` (100% coverage). (`78b2430`)
- 4 schema contract tests for `HYPER_AGENT_SCHEMA`. (`af8cdf6`)
- 1 live integration test (skipped on CI without Ollama). (`45a8f43`)

### Compatibility
No breaking changes. All v1.33.0 + v1.34.0 fixes retained.

## v1.34.0 — 2026-10-21 — performance + retention entry point

### Added
- **scripts/retention.py** — production retention entry point. Dry-run by
  default, `--apply` to delete, `--json` for cron/systemd. Exit codes:
  0 ok, 1 error, 2 cancelled. (`b71fbd6`)

### Performance
- **memory.similar()** — caps at 500-row recency window + new
  `idx_interactions_signal` index. Prevents full-table scan per chat
  message. (`7f1c675`)
- **Council first round** — members fan out via `ThreadPoolExecutor` while
  preserving emission order. 6 members: 1.77s → 0.25s. (`db76db6`)

### Compatibility
No breaking changes. All v1.33.0 security fixes remain in effect.

## v1.33.0 — 2026-10-21 — security hardening (C1-C4 + P0 exposure)

Rolls up the security work merged since v1.32.0: four independently reproduced
fail-open/fail-dangerous findings (C1-C4), a provider-client request budget cap,
and a final sweep that closed the remaining network-exposure vectors. No breaking
API changes; the loopback dev workflow is unchanged.

- **C4 — webhook fail-open (HIGH)**. `webhook_server.py` (root-level)
  `_verify` returned `True` when `WEBHOOK_SECRET` was empty, and the server bound
  `0.0.0.0` — an unsigned POST reached `pr_reviewer.review_pr`. **Fix (same
  pattern as C3): fail closed** — empty secret ⇒ verification fails, and the bind
  host resolves to `127.0.0.1` (with a warning, not a startup refusal — a
  container orchestrator would crash-loop otherwise). `WEBHOOK_HOST` overrides.
  Guard: `tests/security/test_webhook_fail_closed.py` (5).
- **Request budget cap (v1.32.1)**. `src/novamind/core/llm_router.py` built the
  OpenAI client without a timeout, so the SDK httpx default (600s) let a hung
  provider block a caller for ten minutes. **Fix:** `DEFAULT_TIMEOUT=60.0` /
  `DEFAULT_RETRIES=2`, overridable via `NEXUS_LLM_TIMEOUT` / `NEXUS_LLM_RETRIES`.
  Tests: `tests/test_llm_router_timeout.py` (4).
- **P0 exposure sweep — remaining vectors closed**. Five loopback-bind fixes:
  `unified_agent.py` binds `127.0.0.1` (`NEXUS_BIND`; workspace endpoints are
  unauthenticated by design), `src/novamind/core/a2a/server.py` (`NEXUS_A2A_BIND`),
  `src/novamind/dashboard/app.py` (`NEXUS_DASH_BIND`), `webhook_server.py`
  (`MAX_BODY_BYTES=5MB`, 413 before the body is read), and `docker-compose.yml`
  makes `REDIS_PASSWORD` mandatory (`:?`) and moves Redis from `ports:` to
  `expose:`. `.env.example` documents the three bind variables.

C1 (RCE via `run_shell`), C2 (`.env` dump via `safe_path`) and C3 (fail-open
auth off loopback) shipped in v1.32.0 and are unchanged here.

## v1.32.0 — 2026-10-21 — security: three verified vulnerabilities fixed

Three real findings, each reproduced against the running code before the fix
was written. All are reachable without authentication in the default config.

- **C1 — remote code execution via `run_shell` (HIGH)**.
  `src/agent_loop/tools.py` gated a shell tool with a `startswith` allow-list
  and then ran the string with `shell=True`. `cat` was on the list, so
  `run_shell('cat .env')` leaked every provider key, and `ls; cat .env`
  slipped through the prefix check. Reachable through the orchestrator's
  `run_shell|execute` routing. **Fix: deleted the tool** — it duplicated the
  sandboxed `execute_code` in `src/learning/tools.py`. Guard:
  `tests/security/test_no_run_shell.py`.
- **C2 — `.env` dump via `safe_path` (HIGH)**.
  `safe_path` in `unified_agent.py:70` checked only that a path stayed inside
  the project root; `.env` is inside the root. `GET /api/workspace/file?path=.env`
  returned the live keys, and five call sites inherited the hole. **Fix:**
  reused the existing `is_sensitive_file` deny-list (lazy import, same one the
  tool executor uses). Guard: `tests/security/test_safe_path_blocks_env.py`.
- **C3 — fail-open auth off loopback (HIGH)**.
  `AccessGuard.check` gated mutating methods only when a token was configured,
  so a tokenless gateway bound to `0.0.0.0` (the standalone engine,
  `unified_agent.py:553`) accepted anonymous writes from the whole LAN —
  and, chained with C2, an anonymous `.env` read. **Fix: fail closed** — with
  no token set, mutating routes are loopback-only; a remote client gets 401.
  Reads stay free; a configured token still works from anywhere; a wrong token
  is refused even from localhost. Guard:
  `tests/security/test_fail_closed_auth.py`.

No breaking API changes. The loopback dev workflow is unchanged.

## Unreleased — 2026-10-20 — security: STRIDE audit + 3 fixes

- **Security audit (STRIDE)** — full threat model + executable PoC suite:
  `docs/security/threat-model-STRIDE.md` + `tests/security/stride/` (29 vectors,
  6 categories) + `reports/security-audit-2026-10-20.md`. All 29 vectors pass.
- **HIGH — tool executor read the live `.env`** (Information Disclosure): the
  confined `read`/`list`/`grep` tools returned any in-root secret store.
  Fixed with `is_sensitive_file()` deny-list (`.env*`, `id_rsa`, `*.pem`/`key`/
  `p12`/`pfx`/`keystore`, `credentials*`, `secrets.*`, `.git-credentials`).
  `.env.example` stays readable.
- **HIGH — hostile `genome_import` payload → HTTP 500** (Tampering + DoS):
  a non-list / non-dict / non-numeric payload raised `AttributeError`/`ValueError`.
  Fixed at the boundary: shape validation + tolerant `_as_int`/`_as_float`.
- **MEDIUM — `/api/diag` disclosed absolute server paths** (Information
  Disclosure): `loaded_from` is now a bare filename and `sys.path` a count.
- Regression guards: `tests/test_stride_fixes.py` (23).

## v1.31.4 — 2026-10-20 — fix: HIGH tasks could bypass the Jury gate (StrEnum)

- **Security-relevant bug (BUG-C)**: the orchestrator picked a decomposed
  request's overall risk with a bare `max((s.risk for s in subtasks))`. The
  `RiskLevel` enum defined only `__lt__`, so `max()` — which compares with `>` —
  fell back to the inherited comparison and returned the **wrong** level:
  `max([HIGH, MED])` → `MED`. A decomposed **HIGH** request was therefore
  treated as MED and **silently skipped the Jury gate**. Fixed with an explicit
  `key=risk_key` (the new, only-safe sort key). Proven before/after:
  `max([HIGH, LOW, MED])` was `med` → now `high`.
- **BUG-A/B — `(str, Enum)` leaked `"RiskLevel.HIGH"`**: `str(risk)` returned
  `"RiskLevel.HIGH"`, so `str(risk) == "high"` was silently False on every
  boundary. `RiskLevel` / `Complexity` / `Strategy` migrated to **`StrEnum`**
  (Python ≥3.11) → `str()` now returns the value. The custom `__lt__` (and its
  `type: ignore`) were removed; `risk_key()`/`RISK_ORDER` added.
- **Dashboard key mismatch fixed**: `dashboard._RISKS` used `"medium"` while
  live rows carry `"med"` — the med bucket was **always 0**. Now counted
  correctly (live proof: `0 → 47`).
- **API contract unchanged**: `by_risk_requests` stays `{low, med, high}` and
  `by_priority` stays `{low, medium, high}` (a separate ledger). New guard:
  `tests/test_risk_enum_contract.py` (+ the `test_endpoint_returns_med_not_medium`
  integration test and `test_decomposed_high_risk_still_reaches_the_jury`).
- Gate: ruff · mypy **182** (no ignore) · annotations **184** · `make check` =
  3463 passed, 1 skipped. **Supersedes v1.31.2** (the earlier risk-reason fix is
  now structural, not a string-unwrap helper).

## v1.31.3 — 2026-10-20 — fix: HIGH risk reasons were never recorded

- **Bug**: `result["plan"]` is the plan's `__dict__`, so `plan["risk"]` is a
  `RiskLevel` **enum**, not the plain string `"high"`. The metrics recorder
  compared `str(enum)` → `"RiskLevel.HIGH"` against `"high"`, never matched, and
  silently dropped `risk_reason` / `risk_matched` on every real HIGH execution —
  `high_reasons` was always empty in production (v1.31.2). Fixed with
  `_risk_level_str()` (unwraps `.value` before the check).
- **Test gap closed**: the earlier unit test passed a plain `"high"` string and
  hid the bug. Two endpoint tests now drive the real `Orchestrator` end-to-end:
  a HIGH request records `risk_reason "high:genome"` + `risk_matched ["genome"]`,
  and a LOW request omits both.
- Gate: ruff · mypy · annotations clean · full suite green.

## v1.31.2 — 2026-10-20 — test isolation + orchestrator risk breakdown

Two focused fixes on the orchestrator metrics log — no behaviour change to any
execution path.

- **Test isolation (v1.31.1)**: `conftest.py` pinned only
  `NEXUS_INTERACTIONS_DB` / `NEXUS_GENOME_PATH` / `NEXUS_TASK_LOG`. The
  orchestrator metrics (`<repo>/data/metrics.json`, appended on every
  `/api/orchestrator/execute`) were NOT pinned, so any test exercising that route
  polluted the checkout. Now `NEXUS_METRICS_PATH` points at a per-pid temp file,
  with a guard test asserting the resolved default path is not under `<repo>/data`.
- **Risk breakdown (v1.31.2)**: `_metrics.record` now stamps an ISO-8601 UTC
  `ts` on every row and, for **HIGH** rows only, keeps `risk_reason` /
  `risk_matched` (from `risk.explain()`). LOW/MED rows omit the reason keys so all
  records share one flat shape; legacy v1 rows (no `ts`) still load.
  `/api/maintenance/metrics` gains **`by_risk_requests`** (`{low,med,high}` counts
  + `high_ratio` + `high_reasons`), read-only from `_metrics.load()`. Named
  `by_risk_requests` because the recorded field is a *risk level*, not a priority.
- Schema version `1 → 2`. Measured write cost p95 = **2.59 ms** (< 5 ms target).
- Gate: ruff · mypy · annotations clean · **3454 passed, 1 skipped @ 99.66%**.

## v1.31.0 — 2026-10-20 — docs truth + LESSONS (numbers that can't drift)

A documentation-hygiene release. No `src/` behaviour changed — the value is that
the docs stop lying and stop drifting.

- **`.env.example` completed + guarded**: it documented 20 of the 46 env vars the
  code reads. All operator-facing vars are now documented (grouped, one comment
  each) and a new `tests/test_env_docs.py` scans the source and fails if a var is
  read but undocumented (with named allowlists and a sanity test so it can't pass
  vacuously).
- **`AGENTS.md` split**: the tracked root memory had grown to 2346 lines of
  accumulated release notes. Pre-v1.29 history moved to
  `docs/legacy/AGENTS_HISTORY.md`; the root file is now ~223 lines and focused.
  Stale facts corrected along the way.
- **`docs/LESSONS.md` (NEW)**: durable engineering lessons — *manual metrics in
  docs always drift*, *gitignore patterns without a leading slash match anywhere*,
  *read endpoints must be pure*, *never diagnose API behaviour from a screenshot*.
- **README: numbers no longer drift**: the test count was hand-updated four times
  in one session. It now reads `3400+ tests @ ~99%` (and `mypy` without a file
  count) — the precise, always-current value comes from the CI badge / gate run.
- **`docs/genome-stores.md` (NEW)**: documents the two genome stores (v1 SQLite
  council genome vs v2 JSON fitness genome), their bridge, and the deferred
  unification decision.
- **`docs/PROJECT_REVIEW.md`**: addendum for v1.30.0 (W1 fixed, W2 partial, W4
  documented).
- **`.gitignore`**: anchored the `legacy/` rule to `/legacy/` — as an unanchored
  pattern it silently ignored the new `docs/legacy/AGENTS_HISTORY.md`.

## v1.30.0 — 2026-10-20 — real priority ledger (read endpoints stay pure)

The fleet-health view stops lying: `by_priority` was a fixed `{low:0, medium:0,
high:0}` placeholder, so the metrics endpoint could never show what the
maintenance layer actually produced. It now reports a REAL breakdown read from
a new task ledger — and the ledger is written only at the applied boundary, so
a plain `GET` can never mutate state or double-count.

- `src/maintenance/task_log.py` (NEW): an append-only JSONL ledger
  (`$NEXUS_TASK_LOG` → `<repo>/data/task_log.jsonl` → tempdir). `record(...)` is
  non-raising; `aggregate(*, window_days=7, log=None)` returns BOTH a windowed
  view and the all-time totals (with `failure_pct` and `is_sample_sufficient`,
  `MIN_SAMPLE = 30`). Rotates by size (10 MiB × 5), reads its path per write.
- `src/maintenance/api.py`: `metrics_snapshot(*, fitness, log, window_days=7)`
  now emits the real `by_priority` plus `by_priority_all_time` and a `tasks`
  block (`window_days`, `total_all_time`, `failure_pct`, `sample_sufficient`).
  The `# TODO(v1.30)` placeholder is gone. `GET /api/maintenance/metrics`
  accepts `?window_days=`.
- `src/maintenance/task_generator.py`: made PURE again — it only PLANS and never
  writes the ledger. Recording was moved out because the read-only route
  `GET /api/maintenance/tasks` calls `generate_tasks`, so a ledger append there
  let a `GET` mutate state and double-count applied tasks.
- `scripts/generate_tasks.py`: records each task's REAL outcome
  (`generated`/`failed`) right after `/api/orchestrator/execute` — the single
  applied boundary that makes `failure_pct` real.
- `tests/conftest.py`: pins `NEXUS_TASK_LOG` to a per-pid temp file so a test
  never appends to the repo's real ledger. Regression tests assert that neither
  `generate_tasks` nor the `GET` route writes the ledger.

**Live proof** (service restarted to load the fix): ledger reset → `low=0`;
`--apply --max 2` → `low=2` (2 real tasks) and exactly two ledger lines; five
subsequent `GET /api/maintenance/metrics` calls left `low=2` (no pollution).
`GET` latency 9-21 ms — no cache needed, so no `TODO(v1.31)`.

## v1.29.0 — 2026-10-20 — bounded logs, leak guard, fleet-health metrics

Hardening the edges the fleet actually touches: the audit log stops growing
forever, the test suite fails instead of quietly leaking runtime state into the
working tree, and the maintenance layer gains an HTTP surface.

- `src/novamind/core/security_gatekeeper.py`: the audit log now rotates by
  size instead of growing unbounded — `DEFAULT_LOG_MAX_BYTES = 10 MiB` and
  `DEFAULT_LOG_BACKUPS = 5`, overridable via `NEXUS_SECURITY_LOG_MAX_BYTES` /
  `NEXUS_SECURITY_LOG_BACKUPS`. `_rotate_if_needed()` runs before each append;
  `backup_count <= 0` means no retention (the file is removed).
- `tests/conftest.py`: an autouse `_guard_no_runtime_leaks` fixture fails any
  test that leaks runtime state into `memory/`; `pytest_configure` points the
  security log at `tempfile.gettempdir()` so a run never writes into the tree.
- `src/maintenance/api.py` (NEW): `GET /api/maintenance/metrics` (genome
  fitness snapshot + task-priority breakdown) and `GET /api/maintenance/tasks`
  (a bounded batch from `generate_tasks`), mounted via
  `app.router.routes.extend` so they survive the gateway's ASGI mount. The
  genome getters degrade to `{}` on any error — the routes never raise.

## v1.28.1 — 2026-10-20 — test isolation (novamind runtime dirs + security log)

Test runs were writing real runtime state into the working tree: the novamind
suite's directory-based state and a security audit log that had grown to 33 MB
across eight days — invisible to `git status` (gitignored) and to the framework
gate (`--ignore=tests/novamind`).

- `SecurityGatekeeper` honours `NEXUS_SECURITY_LOG` before falling back to
  `memory/security_log.jsonl`, so a test process can be pointed at a temp file.
  Existing behaviour is preserved when the variable is unset.
- The novamind tests are isolated from the repo's runtime directories so a run
  leaves the tree clean.

## v1.28.0 — 2026-10-20 — test isolation (KnowledgeGraph)

The KnowledgeGraph tests wrote into a shared, repo-relative location, so a run
left state behind. They now use `tmp_path` and clean up after themselves.

## v1.27.0 — 2026-10-20 — maintenance & task generation

The genome now drives housekeeping. New, additive-only layer; no existing
file or route changes.

- `src/maintenance/task_generator.py`: reads agent fitness from the genome
  and produces a bounded batch of LOW/MED maintenance requests, weakest
  fitness first. HIGH-risk candidates are filtered out as a last line of
  defence — the generator can never emit a destructive task.
- `scripts/cleanup.py`: dry-run-first repo cleanup (caches + backup junk)
  with a segment-aware guard that refuses to touch `src/`, `tests/`,
  `data/genome.json` and `.git`; logs to `data/cleanup.log`.
- `scripts/generate_tasks.py`: reads `data/genome.json`, asks the generator
  for a batch (cap 10 via `NEXUS_MAX_TASKS`) and POSTs each to
  `/api/orchestrator/execute`; dry run by default; logs to
  `data/generator.log`.
- `tests/test_maintenance.py`: 18 hermetic tests incl. the HIGH-risk guard.

## v1.26.1 — 2026-10-20 — invisible council (decision-only by default)

The council's per-juror debate was leaking to every API consumer: the
`POST /api/orchestrator/execute` response carried the full `member_verdicts`
map on HIGH-risk requests. No shipped page read it, but it was a public
surface. This release hides the debate at the API boundary by default.

- `src/orchestrator/orchestrator.py`: `_apply_jury` now returns
  `{"approved", "confidence"}` only. `NEXUS_UI_VERBOSE=1` restores the full
  verdict (the developer/verbose contract); the flag is truthy-only, so any
  other value keeps the black-box shape.
- `src/novamind/council/jury.py`: `judge()` appends the FULL verdict (per-juror
  detail included) to `data/council_trace.jsonl` (`NEXUS_COUNCIL_TRACE`
  overrides; never raises) so the debate stays auditable even when it is not
  served. Voting logic is untouched.
- No UI change was needed: a repo-wide search found ZERO `.html`/`.js` files
  reading `member_verdicts` or the `jury` object — the black-box shape breaks
  nothing.

## v1.26.0 — 2026-10-20 — verb-alias routing + token-risk tuning

Live batch data (20 requests) showed 3/20 requests scoring 0.0 — the verb shared
no word with any agent scope, so the genome tie-break silently handed them to the
wrong agent (`delete genome entries` → analyst/plan instead of an ops agent).

- **New** `src/orchestrator/aliases.py`: a pure, stdlib-only verb→domain table
  (`optimize`→performance, `delete`→recovery, `rotate`→audit, …). `expand()` adds
  the implied words when scoring; `NEXUS_ALIASES=0` disables it (old behaviour).
- `router.py`: `route()`/`route_with_reason()` score against the expanded tokens;
  the reported `tokens` stay the raw request tokens (diagnostics unchanged).
- `risk.py`: a bare `"token"` is no longer a standalone HIGH pattern — it is now
  contextual (HIGH only beside a destructive/security verb). `token overlap
  search` is MED again, while `delete the token` stays HIGH.
- Verified before/after on the four misrouted requests: `delete genome entries`
  analyst/0.0 → recovery/5.0 · `rotate the auth token` analyst/0.0 →
  security_auditor/4.0 · `delete all training certificates` analyst/0.0 →
  recovery/5.0 · `optimize the token overlap search` performance/2.0 (high) →
  performance/5.0 (med).

## v1.25.0 — 2026-10-20 — orchestrator dashboard (execution metrics)

### Added
- `src/orchestrator/_metrics.py` — append-only, bounded (`MAX_RECORDS=2000`),
  never-raising execution log. Every `POST /api/orchestrator/execute` appends
  one compact record (ok / decomposed / subtasks / agents / failed agents /
  jury / risk). Path: `$NEXUS_METRICS_PATH` → `<repo>/data/metrics.json` →
  tempdir. A damaged or unwritable log degrades to a no-op.
- `src/orchestrator/dashboard.py` — read-only CLI
  (`python -m src.orchestrator.dashboard`) with a pure `summarize()` and
  `render()`. Prints executions, decomposed vs single, the risk mix, the jury
  fire rate, the top agents and per-agent failure rates.
- `nexus_agent.py` — `_record_orchestrator_metric()` is called right after a
  successful execute (jury / decomposed / risk read off the result); every
  error is swallowed so a metrics failure can never break execution.

### Tests
- `tests/test_metrics.py`, `tests/test_dashboard.py` and two wiring guards in
  `tests/test_orchestrator_execute_api.py`.

## v1.24.0 — 2026-10-20 — task decomposition

### Added
- `src/orchestrator/decomposer.py` — a compound request ("write a sum function
  **and** test it") is split into ordered subtasks, each routed to its own agent,
  then merged into one block. Pure module: `split_clauses` (word connectors +
  punctuation, word-boundary safe so "sand"/"android" survive), `SubTask`,
  `decompose` (verb/agent lexicon first, the legacy keyword router as fallback,
  dedupe by agent), `merge_outputs`. Risk is computed per subtask.
- `Orchestrator.execute()` runs the subtasks in order and applies ONE jury
  decision over the merged block at the highest subtask risk. New result keys:
  `decomposed`, `subtasks`, `results`; a runner error is captured per subtask
  and the overall run is `ok=False` if any subtask failed.
- `NEXUS_DECOMPOSE=0` disables the feature — the single-agent path stays
  byte-for-byte identical (no `decomposed` key).

### Fixed
- `Orchestrator.execute()` now surfaces a captured subtask error in
  `results[i]["error"]` instead of dropping it.

## v1.23.0 — 2026-10-20 — version-drift guard + genome bootstrap

### Added
- `scripts/check_version_sync.py` — one guard that keeps the release version
  consistent everywhere it lives: `pyproject.toml` ↔ `src.__version__` (imported,
  not text-parsed) ↔ `docs/openapi.yaml info.version` ↔ the exact git tag on HEAD.
  An **orphan release** (a tag newer than the version files) fails with exit 1.
- `scripts/feed_genome.py` — bootstraps the agent genome with one representative
  task per framework agent (20) through `POST /api/chat {agent: <id>}`, then
  reports which genome rows moved. Uses `/api/chat` deliberately: it names the
  agent, whereas `/api/orchestrator/execute` routes by keyword and has no
  `agent_id` field.

### Changed
- `.github/workflows/ci.yml` — the lint job runs the version guard and now checks
  out with `fetch-depth: 0` so the git tags are present (a shallow checkout has
  none, which would fail the guard for the wrong reason).

### Tests
- `tests/test_check_version_sync.py` (13) — hermetic guards for the readers,
  semver parsing and the orphan-release rule.
- Total: **3299 passed, 1 skipped @ 99.77%** coverage.

### Live verification
- `POST /api/orchestrator/execute` returns `{plan, jury, output, ok}`.
- HIGH-risk `"delete genome entries from the store"` → jury 6/6 approve, conf 0.95.
- `scripts/feed_genome.py` → 20/20 agents answered, **20 genome rows moved**
  (was a single `coder` row).
- After `sv restart`: genome persists **26 agents · 9 judgements · 26 tasks** —
  the disk-restore path works end to end.

## v1.22.0 — 2026-10-20 — orchestrator execute endpoint + jury LLM adapter

### Added
- `POST /api/orchestrator/execute` — classify the request, route it to an agent,
  run that agent for real, and gate HIGH-risk work through the council jury.
  Returns `{plan, jury, output, ok}`. Runs on a thread so a slow provider never
  blocks the event loop.
- `src/orchestrator/llm_adapter.py` — `RouterLLMAdapter` + `adapt_llm`. A thin
  bridge at the boundary: the jury calls
  `generate(prompt, json_mode=True, temperature=0.0)` and expects a raw string,
  while the project router returns a dict and exposes no `json_mode`. The adapter
  normalises dict→text, retries without `json_mode` on `TypeError`, and fails
  closed (`""`) so a broken provider can never crash the gate.

### Fixed
- **Jury ↔ router contract mismatch (latent, production-breaking).** Without the
  adapter every HIGH-risk verdict failed closed with
  `TypeError: unexpected keyword argument 'json_mode'` — the gate silently
  rejected all high-risk work. The adapter is now mandatory on this path.
- **`CouncilMember` used as a jury dict key.** `judge()` maps members to verdicts
  and builds a `You are {id}` prompt, so passing `CouncilMember` objects raised
  `cannot use 'CouncilMember' as a dict key (unhashable type)` on every HIGH-risk
  call. The endpoint now passes member **names** (`[m.name for m in
  COUNCIL_MEMBERS]`).
- Both routes (`/api/orchestrator/plan`, `/api/orchestrator/execute`) are
  reordered before the workbench catch-all `Mount`; the reorder now matches the
  path exactly.

### Tests
- `tests/test_orchestrator_llm_adapter.py` (19): full adapter contract (dict
  router, `json_mode` retry, native `json_mode`, fail-closed on error/not-ok/
  None/missing-generate, `adapt_llm` preserve-vs-wrap) + an end-to-end `judge()`
  verdict through the adapter.
- `tests/test_orchestrator_execute_api.py` (8): route registration, mount
  ordering, LOW-risk skips the jury, empty-request rejection, HIGH-risk convenes
  the jury with the real router (the defect guard), jury rejection fails closed,
  runner failure reports `ok=false`, plan endpoint intact.

### Migration
- None. Pure additive; existing `/api/orchestrator/plan` and `/api/*` untouched.

## v1.21.1 — 2026-10-19 — `POST /api/orchestrator/plan`

### Added
- `POST /api/orchestrator/plan` — classify a request and route it to an agent
  WITHOUT executing it. One file changed (`nexus_agent.py`, +58).

### Fixed
- Route shadowing: `/api/orchestrator/plan` was registered after the workbench
  `Mount("/{path}")` and was unreachable (404). Reordered before the Mount.

### Known limitations (deferred to v1.22)
- Routing precision: `"modify coder module"` → `analyst` (token mismatch).
  Aliases / fuzzy matching are a later improvement.

### Tests
- 3/3 risk classifications exercised (low/med/high); empty request rejected
  (fail-safe).

## v1.21.0 — 2026-10-19 — orchestrator + the council jury gate

### Added
- `src/orchestrator/` — deterministic request handling: `risk.py` (LOW/MED/HIGH
  classification, no LLM), `registry.py` (`AgentSpec` registry),
  `router.py` (keyword routing over the registry), `orchestrator.py`
  (`Orchestrator.plan()` + `execute()`).
- `src/novamind/council/jury.py` — a HIGH-risk-only jury gate with isolated
  per-member voting (`jury.judge`, `JuryVerdict`), hardened against prompt
  injection (`_sanitize_target` + explicit CONTEXT boundaries).
- `skills_registry.json` — 20 agents with domain/scope/schemas.
- Blood-cell architecture: orchestrator (platelets) / workers (RBC) /
  council (WBC).

### Changed
- The council no longer fires on every request — only on `risk=HIGH`.

### Tests
- 25 new tests: `test_orchestrator_{risk,registry,router,integration}.py` +
  `test_council_jury.py`.

### Migration
- None. Pure additive; existing `/api/*` untouched.

## v1.20.2 — 2026-10-20 — genome bridge: the Living Council feeds genome_v2

### Added
- The flagship 6-member Living Council (`/api/council/debate`) now mirrors every
  debate's member judgements into **genome_v2** (the store behind
  `/api/training/fitness` and the Academy panel), instead of feeding the v1
  SQLite genome alone. `genome_v2.observe_council(stances, "approve")` is called
  through a new opt-in `judge=` sink on `Council`.
- Pure helper `judgement_stances()` in `src/novamind/council/council.py` maps
  each member's `standing_delta` to a genome_v2 stance (`approve`/`reject`),
  tolerating malformed rows.

### Fixed
- **Two names for one genome file.** `pyproject.toml` puts both `.` and `src` on
  `pythonpath`, so `novamind.genome_v2` and `src.novamind.genome_v2` were two
  module objects holding two in-memory genomes. `_install_genome_layer()` now
  adopts the canonical copy into the bare name (state + persistence hook) and
  registers it in `sys.modules` under both names.

### Tests
- `tests/test_council.py` (+6) and `tests/test_nexus_agent.py` (+7), including an
  app-level end-to-end assertion that one debate reaches genome_v2, a broken-sink
  fail-safe, and both alias branches. Gate `--ignore=tests/novamind`
  **3234 passed, 1 skipped @ 99.94%**.

## v1.20.1 — 2026-10-19 — tech-debt: writable paths + self-healing monitoring

### Fixed
- **Writable-root fallback (Android/Termux).** Six modules assumed `/var/lib` or
  `/var/log`; on a phone `/` is read-only, so `mkdir` raised `OSError` and every
  agent failed to load through the factory. New `src/novamind/paths.py` adds a
  never-raising fallback chain (`$NEXUS_DATA_DIR` → `/var/lib/nexus` →
  `/var/tmp/nexus` → `~/.cache/nexus` → `<tempdir>/nexus`), wired into
  `memory/engine.py`, `security/audit.py`, `security/rbac_audit.py`,
  `agents/project_manager.py`, `security/auto_worker.py` and
  `interface/unified_bot.py`, each with its own env override.
- **`rbac_audit` caught the wrong exception.** `except PermissionError` never
  fired for EROFS (errno 30 is `OSError`) — now `except OSError`.
- **The LLM monitoring wrapper died on a module reload.**
  `patch_llm_router()` early-returned on its own `_patched` flag, so after
  `importlib.reload(novamind.core.llm_router)` the new `LLMRouter` class was
  left unwrapped and no call was recorded. Arming is now idempotent by
  *inspection* (the wrapper carries `_nexus_monitored`) and the gateway re-arms
  explicitly on load.

### Tests
- `tests/test_paths_fallback.py` (16) and reload-trap regression tests in
  `tests/nexus/test_monitoring.py`. Full suite **3374 passed, 1 skipped,
  0 failed**; gate `--ignore=tests/novamind` **3219 passed @ 99.94%**.

## v1.20.0 — 2026-10-19

- **The genome now survives restarts and knows the whole roster.** Previously
  `src/novamind/genome_v2.py` kept fitness in memory only, so every service
  restart wiped it, and the 20 framework agents were invisible in
  `/api/training/fitness` until they happened to run.
- New `src/novamind/genome_store.py` — the single disk touch-point (the genome
  module itself stays pure, no I/O). `load`/`save` (atomic) /`install`;
  `install(agent_ids)` restores the saved genome, seeds the roster from
  `src/agents/manifest.py::all_manifests()`, and installs a save hook that
  persists every mutation. Path order: `$NEXUS_GENOME_PATH` → sibling of the
  training DB → `<repo>/data/genome.json` → temp dir. A missing/corrupt file
  degrades to an empty genome; a failed save never raises.
- `genome_v2` gained `adopt(other)` (in-place take-over that preserves
  identity), `set_persistence_hook(hook)` and `set_genome_v2(genome)`. A restore
  mutates the shared singleton rather than swapping it, because the council
  engine, the field loop and the gateway all hold a reference to the one genome.
- `nexus_agent.py` installs the layer at startup (`main()` only), logging the
  agent / judgement / task counts.

## v1.19.0 — 2026-10-19

- **Verification by execution — agent output is RUN, not trusted, and repaired
  under the process exit code's judgement.** New `src/verify/` (stdlib-only)
  with `verify_by_execution(...)`, a bounded `fix_loop(...)` and a tolerant
  `extract_code(...)`, served as `GET /api/verify/tools`,
  `POST /api/verify/run`, `POST /api/verify/fix`. The engine runs the code in the
  existing exec sandbox and decides by `exit_code`; the model only proposes a
  repair. `VerificationResult` carries an explicit machine-readable `reason`
  (`ok`, `not-verified`, `did-not-run`, `timeout`, `exit N`, `invalid-tests`,
  `runner-error`, `not-fixed`) — no path claims success without a real run.
- **The exec sandbox is reachable at last.** `/api/exec*` were wired but the
  module behind them could not be imported: `tools/exec_sandbox.py` matched the
  unanchored `.gitignore` rule `exec_sandbox.py` (so a fresh clone raised
  `ModuleNotFoundError`, hidden by a try/except) and the bare-name import needs
  the `tools/` directory itself on `sys.path`. Anchored the ignore to
  `/exec_sandbox.py`, tracked the module and added `<repo>/tools` to `sys.path`.
- **Repair-loop fixes (found by proving the loop live):** the raw model reply
  (a fenced block) reached the interpreter, so Python parsed the fences and the
  loop reported a misleading failure — extraction now happens at the model
  boundary; the sandbox import is self-sufficient from any entry point; an
  unmeasurable run returns the real reason instead of `not-fixed`; and the loop
  stops when the fixer repeats the same code.
- **Proof on the running service (:8000):** `POST /api/verify/fix`
  `{add returns a-b, tests assert add(1,2)==3}` → **passed=true · reason=ok ·
  attempts=2 · exit 1 → exit 0 · clean code**.
- Tests: `tests/test_verify_engine.py` + `tests/test_verify_api.py` = **66**,
  hermetic (injected runner/generator) with real-sandbox cases behind
  `requires_sandbox`; a regression asserts the routes survive an ASGI
  `mount("/")`. `src/verify` = **100% coverage**.
- Gates: ruff clean · annotations 171 · mypy 171 · real gate
  `pytest --cov --cov-fail-under=95 --ignore=tests/novamind` =
  **3177 passed, 1 skipped @ 99.94%**.

## Unreleased

(nothing yet — next changes land here)

## v1.18.1 — 2026-10-19

- **Wiring — the call-monitoring layer (`src/nexus/`) goes live.** It was
  complete and fully tested but imported by nothing, so no LLM call was ever
  recorded (the only writer was a stale `calls_2026-10-14.jsonl`). The gateway
  now arms it on start — importing `src.nexus` auto-patches `LLMRouter.generate`
  via `monitoring_patch` — and serves it:
  `GET /api/monitoring/today`, `GET /api/monitoring/session`,
  `POST /api/monitoring/clear` (token-gated), plus
  `/api/status.components.monitoring`. Every route degrades to
  `{"ok": false, "error": …}` instead of crashing.
- Routes live under `/api/monitoring/*` (not `/api/metrics`) because the engine
  already owns `GET /api/metrics` — a different, never-fed observability counter
  system with no tokens/cost.
- Verified live on `:8000`: one `POST /api/chat {agent: coder}` moved the counter
  from 0 → **2 calls, 1796 tokens, $0.00009** (provider `groq_01`; the chat and
  its reflection call both traverse `LLMRouter.generate`), and
  `calls_2026-10-19.jsonl` was written. `POST /api/monitoring/clear` returns
  **401 without `X-Auth-Token`**, 200 with it.
- Tests: **+6** in `tests/test_nexus_agent.py` (43 in the file) covering the
  armed wrapper, the recorded call, `/api/status`, the routes, and both
  degradation paths. Real gate: **3111 passed, 1 skipped**.

## v1.18.0 — 2026-10-19

- **PR #22 merged (squash)** — Day 4 `consensus` tool + Hyper-Agent 2.0 with
  BYOK connectors (OpenAI / Anthropic / Groq / Ollama / DeepSeek / Gemini),
  the agent API (`POST /api/agent/start`, iteration limits, per-iteration
  JSONL logging), and the protected exec-sandbox wiring.
- Security hardening: `bandit` SAST job at MEDIUM+ severity (no `|| true`),
  `.env.example` (never `.env`), `.github/CODEOWNERS`, and
  `tools/detect_env_imports.py` (AST guard against import-time env reads).
- **CI now fully green**: the 8 pre-existing Tests failures are fixed —
  `FileResponse` moved to the top import (E402), `requires_sandbox` skipif
  guard for the gitignored `tools/exec_sandbox.py`, a TZ-independent
  `get_current_time` test, and `TZ: UTC` pinned in both workflows.
  Local gate: **3105 passed, 1 skipped @ 99.94% coverage**.

**Phase 2 / Day 3 — collab + tools import isolation (المرحلة 2 — اليوم 3).**

- NEW `src/learning/collab.py`: `classify_question` (intent → label rules %),
  `consult` (±5° multi-agent consultation), `multi_agent_consensus`
  (≥2 agents, ≥3 votes, agree ≥66% = strong recommendation / توصية قوية).
  LLM import is lazy (`novamind.core.llm_router`) — module stays phone-safe.
- Day-2 tool relocation: `execute_code` / `query_memory` live in
  `src/learning/tools.py` with `tools/` as the author-owned sandbox package.
- **FIX (exec-sandbox import isolation)**: `_default_exec_runner` now imports
  the sandbox by its top-level name (`from exec_sandbox import …`) instead of
  `from tools.exec_sandbox import …`. The package-qualified import made
  `tools` an undeclared dependency — tripping the adversarial supply-chain
  gate — and broke under the gateway's `sys.path` edits (7 Day-2 tests failed
  with `ModuleNotFoundError: No module named 'tools.exec_sandbox'` when
  `nexus_agent.py` was imported first). Fixes: `tests/conftest.py` puts the
  repo-root `tools/` dir on `sys.path` up-front (order-independent), the one
  monkeypatch key in `tests/test_learning_tools.py` follows
  (`sys.modules["exec_sandbox"]`), and the supply-chain gate's in-tree list
  gains `exec_sandbox` (author-owned repo-root module).
- Tests: `tests/test_learning_collab.py` (15) + Day-2 suites — full gate
  **3048 passed, 1 skipped, 100.00% coverage** (floor 99), ruff/mypy/
  annotations clean.

**Phase 1 — long-term memory + self-evaluation (المرحلة 1).**

- NEW `src/learning/interactions.py`: SQLite-backed field memory (WAL,
  `interactions` table) storing every successful `/api/chat` run as
  question + answer + signal_ok + self_rating + reason/lesson +
  retry_used/retried_rating + awareness_gap. `similar()` does weighted
  token-overlap retrieval (Arabic-aware normalisation, empty answers
  excluded); `recent()`/`count()`/`stats()` for dashboards; per-process
  singleton with `NEXUS_INTERACTIONS_DB` override.
- NEW `src/learning/reflection.py`: pure, never-raises post-answer
  self-evaluation — parses the model's `{"rating","reason"}` JSON first,
  falls back to a keyword scan (excellent → good → poor priority);
  `rating_score` (excellent 1.0 / good 0.75 / poor 0.4) feeds
  `genome_v2.observe_outcome(quality=)`; `should_retry` allows ONE retry;
  `awareness_gap` detects confident-claims-vs-failure mismatches;
  `memory_block` renders similar past answers into the agent prompt.
- Gateway (`nexus_agent.py`): every ok answer is now reflected
  (role="fast"); a **poor** rating triggers exactly one re-generation
  (SSE stays backward-compatible — the retried text is the one streamed);
  the interaction is saved and the genome receives the rating-derived
  quality. All three layers (store, reflection, genome feed) are
  failure-isolated — a broken/disabled store never breaks chat.
- Tests: `tests/test_interactions.py` (43, hermetic — both new modules at
  100% coverage) + 10 new gateway tests in `tests/test_nexus_agent.py`
  (poor→retry once, good→no retry, unparseable reflection, dead provider
  still saves, memory-block injection, disabled/broken store survival,
  genome quality channel, legacy quality=None without a rating).
- CHANGELOG note: version stays 1.17.0 here — the release bump lands with
  the next tagged release, not silently.

## v1.17.0 — 2026-10-18
**Academy fitness now shows the task channel.**

- `FieldLoop.fitness()` rows carry the **real task channel** the framework
  agents feed on every `/api/chat` run: `task_observations`, `task_successes`,
  `task_rate`, `task_ewma`, `task_duration_avg`, `task_last_ok`,
  `task_last_duration` and `task_last_quality`, plus `evidence = judgements +
  tasks` — the count the advice thresholds actually use.
- Agents with **no** task outcomes report **null** task fields (not the genome's
  neutral 0.5), so the dashboard never shows a fabricated 50%.
- Junk stored values (nan, strings, bools) are coerced by `_as_int`/`_as_float`
  so a damaged row renders instead of taking the panel down.
- The Academy fitness tab paints **two lines per row** (`acaJudgeLine` +
  `acaTaskLine`): council judgements, agreements, dissent and summed evidence;
  then the real task runs (or an explicit "no tasks" pill), with six new
  AR+EN i18n keys.
- Commits: `f8fda82` · `e943960` · `67a111b` · `758f032`.
- Gate: 2920 passed, 1 skipped @ 100.00% coverage (floor 95). Live verified on
  the spare `:8011` engine and the production `:8000` gateway.

## v1.16.0 — 2026-10-18
**The genome's task channel is live — every real agent run now feeds it.**

- **Root cause fixed (one file, two names = two genomes).** `src/novamind/genome_v2.py`
  is importable as both `novamind.genome_v2` and `src.novamind.genome_v2`; each
  spelling is a **separate module object**, so the in-memory singleton (the genome
  has no persistence) was duplicated — the Council and the training field could
  feed two unconnected genomes. The canonical spelling `src.novamind.genome_v2`
  (the one `src/council/engine.py` and `nexus_agent.py` already use) is now pinned
  FIRST in the fallback tuples of `field.py::_genome_obj` and
  `engine.py::_feed_genome`. A stale test that read the second copy now goes
  through the canonical name.
- **The second channel is live** (`nexus_agent.py`):
  `_record_task_outcome(agent_id, ok, duration, task)` is called from the
  `/api/chat` generator, which now runs inside `try/finally` with a
  `time.monotonic()` timer. A completed answer records a success, a dead provider
  or a generation error records a failure, and **an empty message is not recorded
  at all** (a `ran` flag) so an accidental empty send cannot pollute fitness.
  Every genome error is swallowed ⇒ a broken genome can never break a chat.
  +5 tests (the fake patches the string `src.novamind.genome_v2.get_genome_v2`).
- **Live proof on the service:** `GET /api/training/fitness` (it reads the same
  singleton as the writer) went 0 → 1 with `coder fitness 0.5833` after ONE real
  `POST /api/chat {agent:coder}`; an empty message left the count at 1.

## v1.15.0 — 2026-10-18
**One access guard for the unified server (token + rate limit + audit log), and an honest spec.**

- **`src/security/access.py` (NEW, stdlib-only and FastAPI-free):** one security
  layer that is unit-testable without a server.
  `AccessGuard.check(method, path, headers, client)` decides, `record()` writes
  one JSON line.
  * **auth** — `NEXUS_AUTH_TOKEN` (empty ⇒ off), compared with
    `hmac.compare_digest`, header `X-Auth-Token`.
  * **rate limit** — `NEXUS_RATE_LIMIT`/`NEXUS_RATE_WINDOW` (default **120/60s**),
    fixed window per `client+path`; refuses with 429 + the seconds left in
    `Retry-After`.
  * **audit log** — `NEXUS_AUDIT_LOG` (JSONL path; `off` ⇒ disabled), rotates
    past `AUDIT_MAX_BYTES`, and **swallows I/O errors** (never fails a request).
  * Only mutating methods are gated (`POST`/`PUT`/`PATCH`/`DELETE`); reads always pass.
- **Wired into the gateway** (`nexus_agent.py`) as ONE HTTP middleware in front of
  every route (workbench + gateway routes + the catch-all engine mount) without
  touching a single route. `/api/status` now reports `guard` (never the token).
  The whole layer is switched off with environment variables alone.
- **`docs/openapi.yaml` is now valid YAML:** three `description` values wrote
  `{...: ...}` inside a plain scalar, so any real YAML parser (and the Swagger-UI
  that serves the file) choked on it — the suite never noticed because it read
  the spec with `re`. Fixed, plus `401`/`429` documented on every mutating route
  and a `securityScheme` for the token.
- **Tests:** `tests/test_security_access.py` (29, hermetic: injected clock, temp
  dirs) = 100% on the module · `tests/test_nexus_agent.py` +6 (token, 429 +
  `Retry-After`, audit through the real server) · `tests/test_openapi.py` +2
  (the spec parses with a real YAML parser; every mutating route documents
  401/429).
- **Gates:** ruff clean · check_annotations 162 files · mypy 162 files ·
  `pytest --cov --cov-fail-under=95 --ignore=tests/novamind` = **2896 passed,
  1 skipped @ 100.00%** (9260 statements).

## v1.14.0 — 2026-10-18
**جينوم الوكلاء v2: قياس دقّة الحكم + ربط مراقِب غير مُقحِم بالمجلس.**
- `src/novamind/genome_v2.py` (جديد): جينوم نقي، stdlib فقط، **hermetic** (بلا
  إدخال/إخراج ولا ساعة ولا عشوائية) يقيس **دقّة حكم كل عضو** — أي موقفه مقابل
  الحكم النهائي. ثلاث ترقيات عن v1: تقليص الثقة `confidence = n/(n+K)` (K=5،
  فلا تبدو عيّنة كاملة واحدة «نخبوية»)، تنعيم EWMA (α=0.35) للأداء الجاري،
  وسمات لكل موقف (دقّة مفصولة حسب الحكم النهائي approve/reject/human_review).
- الربط في `src/council/engine.py` **متوافق رجعياً**: معامل اختياري
  `genome=None`؛ `None` ⇒ المفرد المشترك المستورد تأخيرياً مع متن `False` (فشل
  الاستيراد لا يُسقط النقاش أبداً). أُعيد تسمية نص `_judge` القديم إلى
  `_judge_verdict`، وصار `_judge` يعيد نتيجته كما هي بعد تغذية المراقب — الحكم
  والدرجة **مطابقان بايت-ببايت** افتراضياً، وأخطاء المراقب مُبتلعة، والمواقف
  مفلترة على `self.members`.
- `tests/test_genome_v2.py` (77 اختباراً hermetic): الدوال النقية + الصنف
  `GenomeV2` + ربط المحرّك نفسه (افتراضي/محقون ⇒ نتيجة متطابقة، الغريب مُستبعَد،
  الغياب/فشل الاستيراد عملية لا-أثر، المراقب الرامي مُبتلع).
- البوابات: ruff نظيف · check_annotations 154 ملف · mypy 154 ملف ·
  `pytest --cov --cov-fail-under=95 --ignore=tests/novamind` = **2347 ناجح @
  100.00%** (8643 عبارة، 0 فائت، 1812 فرع)؛ `src/council/engine.py` = 100%.

## v1.13.5 — 2026-10-17
**بوابات CI خضراء بالكامل: إصلاح 20 فشلًا قديمًا في وظيفة Tests.**
- وظيفة Tests في GitHub Actions كانت حمراء بـ **20 فشلًا قديمًا** (كلها تعتمد
  على إضافات اختيارية غير موجودة على CI: امتداد `sqlite-vec`/`vec0.so` وحزمة
  `openai`). الآن = **success على Python 3.11/3.12/3.13** (2441 ناجح، 28
  متخطّى، 0 فاشل).
- `tests/conftest.py`: مسبار مشترك `vec_extension_available()` + علامة
  `requires_vec` — «sqlite-vec» امتداد قابل للتحميل لا وحدة قابلة للاستيراد،
  لذا `importorskip("sqlite_vec")` لا ينفع. طُبّقت على 13 اختبار RAG/متجهات.
- `tests/test_agent_loop.py`: `pytest.importorskip("openai")` على اختبارَي عميل
  openai. `tests/test_misc_coverage.py`: حقن عملاء وهميين بـ`raising=False` (لا
  يُعرّف الاسم `OpenAI` أصلًا حين تغيب الحزمة).
- `src/cli/main.py`: `cmd_review` لم يعد يثبّت مسارات Termux —
  `tempfile.gettempdir()` (تحترم `$TMPDIR`) + إعادة كتابة سطر
  `TARGET = Path("...")` بتعبير نمطي عام؛ الاختبارات صارت مستقلة تمامًا.
- القاعدة المثبّتة: اختبار يحتاج «إضافة اختيارية» يجب أن **يُتخطّى**، لا أن
  يؤكّد وجودها.

## v1.13.4 — 2026-10-16
**المجلس الحيّ: تسمية العضو السادس «Tork Acil» + تثبيت الإصدار.**
- `src/novamind/council/council.py`: `id="turk"`/`name="Turk"` →
  `id="tork_acil"`/`name="Tork Acil"` (والشخصية `system=` تواكب الاسم الجديد).
  العضو الأول في `COUNCIL_MEMBERS` (رئيس الجلسة) يبقى محافظًا على دوره.
- الإصدار المعلَن كان متأخرًا عن الواقع منذ v1.13.3: `pyproject.toml` و
  `CHANGELOG` لم يُحدَّثا، فـ `/api/health` و `/api/status` كانا يبلّغان
  `1.13.1.1`. الآن الإصدار = **1.13.4** من مصدر واحد
  (`pyproject.toml` → `src.__version__` → `docs/openapi.yaml` + `SCOPE.md`).
- ملاحظة توافق: الجلسات المحفوظة قبل v1.13.3 تبقى بـ 5 أعضاء في قاعدة
  البيانات كما هي (لا ترحيل — السجل التاريخي يُحفظ كما كان).

## v1.13.3 — 2026-10-16
**Council: عضو سادس (رئيس الجلسة) — 5 → 6 أعضاء.**
- `src/novamind/council/council.py`: `CouncilMember` جديد في مقدمة
  `COUNCIL_MEMBERS` — رئيس جلسة Council وعضوها الأول: يفتح النقاش بتحديد
  نطاق السؤال، يوزّع المهام حسب التخصص، يجمع الآراء ويلخّصها، يقترح القرار
  النهائي، ثم يسلّم الكلمة للخبير للتحقق. القدرات: ابتكار + حماية مصالح +
  رصد مخاطر + برمجة كاملة (frontend/backend/devops/security).
- الأثر: `council_members` في `/api/status` = 6، والجلسات الجديدة
  تبدأ بالرئيس ثم تتابع بقية الأعضاء (analyst → critic → visionary →
  pragmatist → expert). `MAX_MEMBERS=7` بقي كما هو (هامش لعضو سابع).

## v1.13.1.1 — 2026-10-16
**Error memory wired into the LLM router — every provider failure is recorded.**
- `src/novamind/core/llm_router.py`: guarded import (`HAS_ERROR_MEMORY` +
  `try/except`) and a `log()` call inside the `except` branch of
  `LLMRouter.generate`. Each failure records `error_type` (e.g. `AttributeError`),
  `context` (e.g. `provider=broken-test`), the provider name, the role and a
  500-char-truncated `error_message`.
- Effect: one line per provider failure is appended to
  `~/.nexus/error_memory.jsonl` (the raw material for future error-pattern
  analysis). A failure inside `error_memory` itself never breaks the LLM call.
- Verified: a deliberately broken provider → exactly one log entry.

## v1.13.1 — 2026-10-16
**Error memory (first wire) — an append-only JSONL log of LLM failures.**
- `src/novamind/error_memory.py` (new, 57 lines): `ErrorMemory` singleton
  (`get()`) with `log(error_type, context, error_message, **extra)` (append),
  `recent(n)` (last *n*) and `stats()` (counts by type). Stores one JSON object
  per line in `~/.nexus/error_memory.jsonl`.
- `tests/test_error_memory.py` (new, 6 tests): file write, stats-by-type,
  recent-returns-last-n, message truncation, extra-kwargs stored, singleton
  identity.

## v1.13.0 — 2026-10-16
**Unified server (`nexus_agent.py`): one FastAPI app that wraps every layer
without losing a feature — gradual unification *with separation*.**
- **Wrap, don't rewrite (`main.py` is imported intact):** `nexus_agent.py`
  loads `main.py` by path under a private module name (`_nexus_workbench`) and
  reuses its `app` object, so all Workbench routes stay byte-for-byte:
  `/api/deliberate` (SSE), `/api/build(s)`, `/api/craft` (real), `/api/history`
  (+search), `/api/topics`, `/api/stats`, `/api/review`, PWA, Swagger. Loading
  by path avoids the `main` name collision (novamind ships its own `main.py`).
- **NovaMind Living Council + Genome added on the same app:** `/api/council/
  debate`, `/api/council/stream` (SSE), `/api/council/sessions[/{sid}]`,
  `/api/genome`, `/api/genome/{id}`, `/api/genome/{id}/reset`,
  `/api/genome/{id}` (PATCH persona), `/api/genome/export|import`.
- **Framework surface:** `/api/agents` (the real 20 built-ins from
  `AGENT_CLASSES`, not a hardcoded count), `/api/status` (unified component
  report) and a real `/api/chat` (SSE via novamind `LLMRouter`, honouring an
  agent's `system_prompt`) — replacing the old echo stub.
- **No `from __future__ import annotations`** (like `main.py`) so Pydantic
  models bind real types regardless of how the module is loaded.
- 32 routes total (19 Workbench + 13 NovaMind/framework). Version → 1.13.0.

## v1.12.1 — 2026-10-15
**Spec truth: the OpenAPI contract now matches the code, and a guard keeps it
that way.**
- **OpenAPI spec (`docs/openapi.yaml`, new):** describes the REAL routes and
  fields only — `/api/{health,deliberate,history,history/{rec_id},stats,topics,
  build,builds,builds/{build_id},craft}`. It documents the honest error model
  (`/api/craft` and `/api/build` answer **HTTP 200 with `ok=false`** on
  functional failure) instead of promising fields that never existed.
- **Local Swagger UI (`docs/swagger.html` + `docs/vendor/`, new):** served from
  the repo, **no CDN** — `/docs/swagger` works fully offline. `main.py` now
  serves `/api/openapi.yaml`, `/docs` (redirect), `/docs/swagger` and
  `/docs/vendor/{file}`; FastAPI's default CDN docs are turned off
  (`docs_url=None, redoc_url=None`).
- **Optional auth:** set `CRAFT_AUTH_TOKEN` to require `X-Craft-Token` on
  `/api/craft` and `/api/build` (disabled by default — the server binds
  127.0.0.1 only).
- **Drift guard (`tests/test_openapi.py`, new):** fails the suite if a real
  route is undocumented, if the spec promises a phantom route, or if the spec
  reintroduces a fabricated field (`size_bytes`, `proof.command`, `success`).

## v1.12.0 — 2026-10-15
**Craft mode + all quality gates green repo-wide.**
- **Craft (`src/council/craft.py`, new):** generate real code from a free-text
  brief — the LLM emits strict JSON `[{"path", "content"}]`, a path-safety gate
  reuses the builder's `_safe_rel_path` + `ALLOWED_EXT`, artifacts are written
  to `builds_root()/craft_<ts>`, and every `.py` gets a mandatory `py_compile`
  **proof** (`proof.ok=false` on failure — never a silent success). An optional
  `review=true` asks the council to vote on the generated code. Caps:
  `MAX_FILES=10`, `MAX_BYTES=50_000`, `MAX_TOKENS=3500`.
- **Server (`main.py`):** `POST /api/craft` (query + optional review); `src/` is
  now put on `sys.path` at startup so `novamind` imports resolve (the council no
  longer falls back to silent offline).
- **Console (`index.html`) — non-invasive v1.12 module** (a third wrapping
  `<script>`, never edits the originals): **`/session`** = continuous voice
  conversation (STT → deliberate → TTS loop, `توقف` / Esc to end) and
  **`/craft <desc> [review]`** prints the files + the `py_compile` proof +
  optional council review.
- **Quality gates green repo-wide, one consistent scope** (framework surface
  gated; opt-in `novamind` + workbench/web layers excluded and verified by
  their own tests):
  - `ruff check .` → **All checks passed** (was 68 errors).
  - `mypy zyvo-telegram.py zyvo-voice.py src` → **103 files, no issues**.
  - `python scripts/check_annotations.py` → **103 files** OK.
  - `pytest --cov --cov-fail-under=95 --ignore=tests/novamind` → **1848 passed,
    98.94%** (was 81% and failing the floor).
  - Adversarial → **92/92 held (100%)**. The long-red
    `test_supply_chain_imports_are_stdlib_only` is fixed: it now reads declared
    deps live from `pyproject.toml` and fails on any **undeclared** import.
- Declared the missing real dependencies (`rich`, `python-dotenv`, `pydantic`) +
  a new `embeddings = ["openai>=1.0"]` extra.
- Fixed the **telegram orphan-brain** bug: install SIGTERM/SIGINT/SIGHUP
  handlers that kill the spawned brain, so a runit restart no longer leaves an
  orphan holding the port.
- Repository hygiene: `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CITATION.cff`, issue
  / PR templates, Dependabot, a unified `make check`, and a refreshed README.
- Version 1.11.0 → **1.12.0** (`pyproject.toml` + `src/__init__.py`; `/api/health`
  reads it live).

## v1.11.0 — 2026-10-15
**Voice & modern UX (workbench console).**
- **Server (`main.py`):**
  - `/api/history` accepts `q` (text search) and `limit` (1–200). Empty `q`
    keeps the previous "recent" behaviour. Backed by a new
    `CouncilHistory.search()` (`src/council/history.py`) — case-insensitive
    match over query/reasoning/topic/category, newest-first.
  - **PWA routes**, served inline (no extra files): `/manifest.json`,
    `/sw.js` (network-first for the shell, never caches `/api/*` so SSE stays
    live), `/icon.svg` (theme-coloured council glyph).
- **Console (`index.html`) — non-invasive v1.11 module** injected as a second
  `<script>`; it **wraps** the existing `handleEvent` / `deliberate` /
  `command` functions (all top-level `function` declarations → present on
  `window`) and never edits the originals. If a wrap fails it emits a yellow
  warning instead of breaking the console.
  - 🎤 **Voice input** (Web Speech API `ar-SA`) → fills the query / runs the command.
  - 🗣 **Voice output** — on a verdict, speaks the result + recommendation.
  - 🔊 **Generated sound effects** (Web Audio, no audio files) for
    verdict/error/tick; toggleable.
  - 🔎 **`/search`**, ⤴ **share** (Web Share API → clipboard fallback),
    ⬇ **`/export`** (downloads the console transcript).
  - New commands: `/voice on|off`, `/say نص`, `/search كلمة`, `/share`,
    `/export`, `/nx`. Settings persist in `localStorage` (`nx_*`).
  - Registers the service worker + injects the manifest/theme-color on load.
- Version single-source aligned to **1.11.0** (`pyproject.toml` +
  `src/__init__.py`; `/api/health` reads it live).
- Verified: `py_compile` clean, `/manifest.json` `/sw.js` `/icon.svg` →
  HTTP 200, `/api/history?q=…&limit=…` (Arabic + English + no-match) correct,
  headless Chromium renders the `✦ v1.11` banner with **no wrap warning** and
  the service worker registered; `tests/council` 93 passed.

## v1.10.1 — 2026-10-15
**Hygiene + suite repair (reported from a v1.10.0 review).**
- Recommendation filter: **verdict words** (`آمن/امن/غير آمن/خطر/مقبول/مرفوض/محايد`)
  are no longer accepted as recommendations. The check uses `startswith`
  (not `in`) so legitimate `نعم`/`لا` answers and words like `سلامة` survive.
  Patch target is `src/council/recommend.py` — the v1.9.2 refactor moved this
  logic out of `main.py`, so the reviewed draft's path was stale.
- **Single version source**: `/api/health` now returns `version`, read from
  `pyproject.toml`; the console header renders `h.version` instead of a
  hardcoded `v1.10.0`. `pyproject.toml` + `src/__init__.py` aligned to 1.10.1.
- **Suite repair (two real, pre-existing collection/ordering bugs):**
  - `tests/test_zyvo_{telegram,voice}.py` imported top-level `conftest`, which
    resolved to `tests/novamind/conftest.py` once the novamind extras (fastapi)
    became installed — an `ImportError` that aborted collection of the whole
    suite. Fixed to `from tests.conftest import ...`.
  - `tests/test_build_api.py` did a bare `import main`; the novamind suite puts
    `src/novamind` on `sys.path`, so `main` resolved to `src/novamind/main.py`
    (no `app`) and all 6 builder-API tests errored. The workbench app is now
    loaded by explicit path (`importlib.util.spec_from_file_location`), making
    the tests order-independent.
- New regression test for the verdict-word filter
  (`tests/council/test_recommend.py`).

## v1.9.3 — 2026-10-15
**Embedding-provider correctness (prep for real embeddings).**
- `src/memory/providers/openai.py` was a byte-for-byte copy of `gemini.py`
  (carried a stray `GeminiEmbeddings` class + the wrong module docstring) —
  the duplicate was removed and the docstring fixed.
- `HashingEmbedder` now exposes `.embed()` (alias of `__call__`) so it
  actually satisfies the `EmbeddingProvider` protocol that
  `src/memory/providers/base.py::get_provider` returns.
- First tests for the provider registry (`tests/test_memory_providers.py`).

## v1.9.2 — 2026-10-15
**Cache safety + full cache-hit (items ①②⑤).**
- The council cache now persists the **full transcript** and the
  `consensus` flag, so a cache hit returns real member replies — the
  `final_verdict` recommendation is no longer empty on repeat questions.
- **`CACHE_VERSION`** added: bump it when the prompt/logic changes and every
  stale entry is ignored automatically (stats reports `stale_entries`).
- Recommendation extraction was lifted out of `main.py` into the pure,
  tested `src/council/recommend.py::extract_recommendation`.

## v1.9.1 — 2026-10-15
**Cache safety.**
- `rag_bridge` reads the cache's `transcript`/`consensus` fields with
  `getattr` so a cache written by an older version can never raise
  `AttributeError` on a cache hit.

## v1.9.0 — 2026-10-14
**Early-consensus + majority recommendation.**
- **Early-consensus**: if the independent phase already has a clear
  agreement, the debate rounds are skipped — 3 LLM calls instead of 6
  (~3.5s instead of ~10s per deliberation).
- **Majority recommendation**: the `final_verdict` recommendation is now a
  majority vote over the members' `[التوصية: …]` lines, filtered so
  meta-words (`analyst`, `اقصر`, …) never leak into the answer.

## v1.7.0 — 2026-10-14
**Unify the RAG write path.**
- `history.save` is now the **single source** that writes decisions into
  RAG; the duplicate write in `rag_bridge` was removed (no more
  double-insertion / echo-chamber twin entries).

## v1.6.2 — 2026-10-14
**Distance threshold fix (L2 units).**
- `DISTANCE_THRESHOLD` corrected 0.5 → 0.9: sqlite-vec returns **L2**
  distance (not cosine), so 0.9 ≈ cos > 0.60. The 0.5 value from v1.6.1
  silently dropped almost every real match.

## v1.6.1 — 2026-10-14
- Re-calibrated `DISTANCE_THRESHOLD` 1.15 → 0.5 for HashingEmbedder v2.
  (Superseded by v1.6.2 — 0.5 was measured against cosine, not L2.)

## v1.6.0 — 2026-10-14
**HashingEmbedder v2 — Arabic-native.**
- Arabic normalisation (strip tashkeel, unify hamza / ta-marbuta / ya).
- Arabic + English stopword removal.
- Word **bigrams** added to the feature set (word + char n-grams).
- Deterministic, dependency-free, phone-safe (no numpy / sentence-transformers).

## v1.5.4 — 2026-10-14
- Closed-loop learning wired into the **web** path (`deliberate_streaming`),
  not just the CLI.
- Stopword-filtered overlap for prior-decision hints; "reference only — not a
  verdict" framing.

## v1.5.3 — 2026-10-14
**Closed-loop learning (CLI).**
- Before judging, the engine retrieves similar past decisions and gives them
  to the members as reference-only context (`_past_hint`).

## v1.5.2 — 2026-10-14
- Similarity threshold 1.15 + corrected RAG framing: injected knowledge is
  explicitly labelled "reference, not a verdict".

## v1.5.1 — 2026-10-14
**Structural correctness release.**
- **Echo-chamber guard**: prior Council verdicts (`[Council …]`) are excluded
  from RAG recall — they are decisions, not evidence.
- **Consensus semantics**: the `consensus` field now reflects actual agent
  agreement (not a raw threshold comparison).
- Housekeeping: untracked `engine.py.pre_streaming`; renamed the legacy
  `v1.0.0` tag → `v1.0.0-old`; `.pre_*` / `*.backup*` added to `.gitignore`.

### Verification
- "TypeScript vs JS" → approve (0.85), consensus=true, rec=TypeScript
- "Ignore test failures" → reject (0.15), consensus=true, rec=البديل

## v1.5.0 — 2026-10-14
**First stable release (council workbench).**
- 79 agents, 8 categories
- Hybrid Router (code / tool / decision)
- Council with real LLM streaming + 24 topics
- RAG with sqlite-vec
- 13 CLI tools, Web Workbench
- 41 pytest tests, 100% pass

## v1.0.0 — 2026-10-14
**Unified merge baseline (`v1.0.0-old`).**
- Merge of the 20-agent framework (`tyb-zyv-ai`) and the orchestration layer
  (`novamind-core`) into one repo.
- 20 agents across core / planning / quality / ops.
- Council of 3 agents, RAG, loop engine, security scanner, session cache.
- 13 CLI tools, Web Workbench, Python API, 16 REST endpoints.

## v0.23.x
- Streaming fixes, real verdicts, recommendation.

## v0.22.0
- Live SSE streaming.

## v0.9.0 – v0.21.0
- Incremental: registry, RAG, Council, Web, Router, 24 topics.
