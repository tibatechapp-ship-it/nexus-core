# nexus-core — project memory

Unified AI Agent System: **Memory + Learning + Security + 20 Agents** — the
merge of tyb-zyv-ai (stdlib-only 20-agent framework + TUI) and novamind-core
(server-side orchestration). v1.0.0 → v1.5.0, MIT, repo
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

## v1.5 — chat server: SQLite + Time Machine + web UI
- `src/novamind/core/session_store.py`: stdlib SQLite store (WAL,
  connection-per-op, PRAGMA user_version). Tables: conversations, messages,
  council_sessions, council_messages (reserved for the v2.0 Council), traces
  (Time Machine). `default_db_path()` = `$NEXUS_DB` → `<repo>/data/sessions.db`
  → `$TMPDIR` fallback; `get_store()` process singleton. Pure stdlib so the
  phone gate + CI both run it with no extras.
- `unified_agent.py` (root FastAPI): serves `web/unified_ui.html` + JSON API.
  `/api/chat` streams SSE (`plan`/`chunk`/`pre_check`/`error` … `[DONE]`) and
  now logs a trace per request (ChatRequest carries conversation_id + agent).
  Conversation CRUD + `PUT` = client-authoritative full-thread sync;
  `/api/traces[...]` (list/get/export json|md/replay/delete/clear);
  `/api/export/conversations`; `/api/db/stats`.
- `web/unified_ui.html`: DB-first chat UI (RTL ar + en). localStorage is only a
  fallback mirror; first boot migrates it via `/api/conversations/migrate`.
  Time-Machine modal (topbar clock, Ctrl+Shift+T), pin / inline rename /
  export+import, Markdown tables + images, copy/regenerate/edit, agent picker.
- Run: `PYTHONPATH=src/novamind:src:. python unified_agent.py` → :8000.

## v2.0 — The Living Council (المجلس الحيّ)
- `src/novamind/council/council.py` (+ `__init__.py`, RELATIVE imports so
  `novamind` and `src.novamind` don't double-import under pytest's
  `pythonpath`): 5 specialised members (analyst, critic, visionary,
  pragmatist, expert) debate a topic over 1–5 rounds with LIVE SSE streaming,
  per-round consensus (largest agreeing fraction by token-Jaccard), early stop
  at ≥ 0.8, and a chief verdict; each member's standing rises/falls by
  alignment with the verdict (`influence`).
- Pure helpers (unit-tested, no deps): `jaccard/position/consensus/influence`.
- Tunables: `CONSENSUS_SIM=0.45`, `CONSENSUS_THRESHOLD=0.8`, `EARLY_MIN_ROUND=2`,
  `MAX_ROUNDS=5`, `MAX_MEMBERS=7`, `GENERATE_TIMEOUT=60.0`, `OFFLINE_CACHE=60.0`.
- Works OFFLINE: no live provider → deterministic local simulation (tests + the
  phone gate never need the network). A live failure flips the run to offline
  for OFFLINE_CACHE=60s (self-healing); each live call is bounded by
  GENERATE_TIMEOUT so a hung provider can't stall a debate. NOTE: a live
  `zai_glm` call can take 15–48s → a full live debate is ~1–3 min.
- Store: `council_sessions`/`council_messages` tables (already in the v1.5
  schema). API: `POST /api/council/stream` (SSE events session/round/
  member_start/member_message/consensus/verdict/done), `POST /api/council/debate`
  (sync), `GET /api/council/sessions`, `GET|DELETE /api/council/sessions/{sid}`.
- UI: ⚖️ topbar button → council modal (topic, rounds, live member chips +
  bubbles, consensus bars, verdict card + influence, history).
- Tests: `tests/test_council.py` (27).

## v2.0 — Agent Genome (جينوم الوكلاء)
- `src/novamind/genome/scoring.py`: pure scoring (no I/O). `success_rate`,
  `avg_latency`, `consensus_avg`, `speed_score`, `compute_standing` (weighted
  0.6 success / 0.3 consensus / 0.1 speed → 0-1), `classify` →
  `promoted` (≥0.7) / `active` / `probation` (<0.4). Neutral standing 0.5.
- `src/novamind/genome/genome.py`: `Genome` manager over the store — `seed`
  (idempotent, carries emoji in meta), `record`, `outcome_from_influence`,
  `reset`, `rank`, `detail`, `export`/`import_`. The store stays a dumb DB; the
  manager owns the scoring math (no import cycle).
- Store `agent_genome` + `genome_events` tables (SCHEMA_VERSION=3) with
  `upsert_agent/get_agent/list_agents/update_agent/record_agent_outcome/
  reset_agent/agent_timeline/genome_import`; `stats()` now has `agents`.
- Council→genome loop: after the verdict, `debate_stream` calls
  `genome.outcome_from_influence` per member (success = standing_delta>0,
  consensus=round score, latency from elapsed_map, detail={session}). Wired via
  `Council(genome=...)`; leave it None → council runs unchanged (back-compat).
- `unified_agent.py`: imports `COUNCIL_MEMBERS` + `Genome`; `get_genome()`
  singleton seeds from `COUNCIL_MEMBERS`; `get_council()` passes it. Endpoints
  `/api/genome` (+ `/{id}` GET/PATCH, `/{id}/reset`, `/export`, `/import`).
- UI: 🧬 topbar button → genome panel (ranked rows, 🥇🥈🥉, standing bars,
  status pills; detail = stats + editable persona + re-train + timeline).
- Tests: `tests/test_genome.py` (31, incl. the council↔genome loop).

## v2.0 — PWA + offline
- `web/manifest.json` (ar RTL, theme #212121, shortcuts for council/genome),
  `web/sw.js` (precache shell, network-first GET /api/* + cache fallback,
  offline.html navigation fallback), `web/offline.html`.
- Icons drawn by a stdlib-only PNG writer (no Pillow on the phone):
  `icon-192/512` + `icon-maskable-512`.
- Server routes: `/manifest.json`, `/sw.js` (Service-Worker-Allowed: /),
  `/offline.html`, `/icon-{192|512|maskable-512}.png` (FileResponse).
- Offline message queue lives CLIENT-SIDE (IndexedDB `nexus_queue`): `send()`
  enqueues when `!navigator.onLine`; `flushQueue()` replays on `online`; badge
  `#qBadge` shows pending count. The SW never queues POSTs (keeps SSE intact).

## v2.0 — autopilot SCM layer (Slice 1, read-only) — 2026-10-13
- `src/novamind/autopilot/scm/`: provider-agnostic source-control access.
  `base.py` (Issue/Change/Response + `SCM`/`SCMWriter`/`Transport` protocols +
  helpers normalize_state/label_names/as_int/retry_after_seconds),
  `exceptions.py` (`SCMError`→Auth/NotFound/RateLimit/Transient + `error_for_status`),
  `transport.py` (`UrllibTransport` stdlib + `RecordingTransport` test double),
  `github.py`/`gitlab.py` (read adapters).
- Slice 1 is READ-ONLY: `GitHubSCM`/`GitLabSCM` implement `SCM` but NOT
  `SCMWriter` (contract tests assert this). Methods: whoami/list_issues/
  get_issue/list_changes/get_change. `_json` wraps malformed bodies as
  TransientError (never leaks JSONDecodeError).
- Provider quirks absorbed: GitHub filters `pull_request` items out of issues
  and paginates via the `Link` rel="next" header; GitLab uses `iid` as the
  per-project number, `description`, `author.username`, encodes `group/proj`
  as `group%2Fproj`, maps state open→opened, paginates via `X-Next-Page`.
- Tests: `tests/test_autopilot_scm_{base,github,gitlab,contract}.py` (70 tests)
  + `tests/fixtures/scm/*.json`; fully offline (RecordingTransport).
- GATE (autopilot measured separately — repo coverage omits src/novamind/*):
  `COVERAGE_RCFILE=coverage-autopilot.ini python -m pytest
  tests/test_autopilot_scm_*.py --cov=src/novamind/autopilot
  --cov-report=term-missing --cov-fail-under=95` → 100%. `coverage-autopilot.ini`
  is the dedicated profile. mypy: pass explicit FILES (config excludes
  src/novamind, so a directory arg reports "no .py files").
- pyproject ruff `extend-exclude` also excludes `docs/legacy` (archived files
  were breaking `ruff check .`). All framework gates green: ruff check . clean,
  mypy 95 files, check_annotations 95 files, pytest 1382 passed @ 98.78%.

### Slice 1 improvements (2026-10-13): resilience + docs
- `scm/transport.py` grew a stackable resilience layer (all stdlib, all
  offline-testable): `RateLimiter` (token bucket, injectable clock),
  `RateLimitedTransport` (throttle + honors 429 `Retry-After` → `penalize`),
  `CachingTransport` (bounded+TTL GET cache, `stats()`/`CacheStats.hit_rate`).
  Stack: `RateLimitedTransport(CachingTransport(UrllibTransport()))`.
- Logging basics: package logger `novamind.autopilot.scm` (NullHandler in
  `scm/__init__.py`), DEBUG on requests/cache, WARNING on HTTP failures.
- README per module: `autopilot/README.md` + `scm/README.md` (ASCII diagrams,
  API tables, provider-difference table, error model).
- MEASURED numbers (deterministic fake-clock tests, NOT claims):
  rate=5/s burst=1 → 11 calls span exactly 2.00s; 10 identical GETs → 1 upstream
  call, 9 saved, hit_rate 0.90. Marketing "80%/90%" figures are NOT used.
- Tests: `tests/test_autopilot_scm_resilience.py` (+20) → 90 autopilot tests,
  100% coverage. Full framework suite: 1402 passed @ 98.78%.

## v2.0 — autopilot readers (Slice 2, read-only) — 2026-10-13
- `src/novamind/autopilot/readers/`: turn provider issues into structured,
  ranked work. `task.py` (frozen `Task` + KINDS/PRIORITIES + `normalize_title`/
  `fingerprint`/`priority_rank`/`kind_rank`), `classify.py` (pure:
  classify_kind/priority, extract_areas/criteria/references, needs_more_info,
  word_count), `reader.py` (`IssueReader(scm, min_body_words=8)` with
  read/read_one/to_task/collect + pure `dedupe`/`rank`/`select`), `__init__.py`
  (surface + NullHandler "novamind.autopilot.readers").
- Mapping: kind from labels (bug/feature/docs/question/chore; `type:`/`kind/`
  prefixes stripped, keyword fallback) → priority from labels (p0..p3/none;
  `priority:high`, bare `priority:2`) → areas (`area:auth`, `component-ui`,
  file paths) → criteria (checkboxes, else bullets under an "acceptance
  criteria"/"definition of done" heading) → references (URLs + `#NNN`) →
  needs_info (triage label, or no criteria AND body < min_body_words) →
  fingerprint (sha256 of normalised title+kind, ignores platform/number → dedup).
- `collect()` composes read→dedupe→select→rank. `select` filters kind /
  priority_max (ceiling) / areas / include_needs_info. `rank` sorts priority,
  kind, title. All read-only; no write surface.
- Tests: `tests/test_autopilot_readers_{parse,reader}.py` (+96). GATE (autopilot
  profile): `COVERAGE_RCFILE=coverage-autopilot.ini python -m pytest
  tests/test_autopilot_*.py --cov=src/novamind/autopilot` → **186 tests, 100%**.
  mypy on autopilot = pass explicit FILES (`mypy src/novamind/autopilot/readers/*.py
  src/novamind/autopilot/scm/*.py`) — explicit args override the config exclude.
- README per module: `readers/README.md` (API table, mapping rules); autopilot
  README slice table now shows 2 = shipped, 3 = next.
- Full repo gates green after Slice 2: ruff check . clean, mypy framework 95
  files, check_annotations 95 files, `pytest --cov` 1498 passed @ 98.78%.

## Live test finding — agents + git tools (2026-10-13, real LLM)
- Smoke test on commit 1045b54 (real ZYVO brain :4141, Big Pickle): direct git_tools
  PASS 4/4; MCP echo plumbing PASS (5 git tools registered). BUT **real-LLM agents
  executed ZERO tools**: analyst emitted `<tool-call name="git_status"></tool-call>`
  (no `args=` attr) and `<tool-call name="git_log">\n{...}\n</tool-call>` (args as
  child text); reporter answered WITHOUT any markers. Root cause =
  `src/tools/executor.py::_TOOL_CALL_RE` requires `name="..." args="..."` — the
  model's alternate dialect is ignored silently (loop breaks, 0 outcomes, ok=True).
- Results JSON: `tests/_intelligence_results/{git_tools_smoke,git_tools_agents}.json`.
  FIX OPTIONS (await tyba): (a) harden `parse_tool_calls` — accept missing args→{}
  + child-text JSON args + `<name></name>` pair form; (b) strengthen the
  build_messages tool syntax instructions. Unfixed: `parse_tool_calls` stays strict.
- The brain for these runs: `zyvo --port 4141` (PID noted in session), killed on
  request; the runit telegram service (4142) is separate.

## Ops fix — telegram chat-filter fallback (2026-10-13)
- Commit `f09a41a` (pushed origin + gitlab): `zyvo-telegram.py` only ever read
  `ZYVO_TELEGRAM_CHAT_ID`; a `telegram.env` carrying the generic
  `TELEGRAM_CHAT_ID` left `ALLOWED_CHAT=""` → the poll loop accepted ANY chat.
  New tested `_resolve_allowed_chat(cfg)` — precedence ZYVO env → ZYVO file →
  TELEGRAM env → TELEGRAM file (app-specific key beats generic; env beats file);
  the same fallback mirrored in `scripts/health_monitor.py main()`. Test
  `test_resolve_allowed_chat_precedence` in `tests/test_zyvo_telegram.py`
  (+1 → 96 in that file). Gates after: framework 1499 passed, autopilot 186 @
  100%, ruff/mypy/check_annotations clean.
- NOTE: the running copy is `~/bin/zyvo-telegram.py` (runit service), NOT the
  repo file — keep the two byte-identical; `~/bin` copy was edited too. The
  service was DOWN (`sv status` → "runsv not running"); start via
  `sv up zyvo-telegram`.
- Audit (read-only, 2026-10-13): tracked-file secret scan CLEAN (all hits were
  scanner regex + test fixtures; `.env` untracked). `src/security` scanner
  verdict on `src/` is dominated by self-referential false positives (the
  scanner's own detector regexes/training-task strings). Two files with
  `subprocess(..., shell=True)` at root — `hive_agent_smart.py:46`,
  `hive_security_scanner.py:84` — are standalone leftovers NOT imported
  anywhere; cmd is internally built with guards (blocks force-push/reset
  --hard/rm -rf). `scan_path` single-FILE bug FIXED 2026-10-13 (see below).

## Security audit + hardening (2026-10-13)
- Scope: bandit + pip-audit + ruff + mypy + dangerous-pattern/secret grep over
  src/, then fix the critical findings, then low-risk improvements. No new
  side files (no SECURITY.md/Dependabot). `safety` is unusable on Termux
  (its `cryptography` wheel fails to dlopen on Python 3.14) → used `pip-audit`
  instead: `pip-audit -r requirements.txt` → no known vulnerabilities.
- Bandit BEFORE: 6 High / 38 Medium. AFTER: 0 High. All 6 High were B324 —
  `hashlib.md5(...)` used for NON-cryptographic IDs (dedup keys, fingerprints,
  cache hashes) in reflective_rag, immune_network, loop_engine, waste_detector,
  watcher → fixed by adding `usedforsecurity=False` (identical digest, marks
  intent, silences the scanner). The 38 Medium are false positives / by-design:
  B608 SQL (static table names + allowlisted columns, values parameterized),
  B105/B107 "password" (severity/label strings + empty token defaults),
  B310 urlopen (FetchURLTool already guards the scheme; the rest hit fixed
  configured endpoints), B104 bind-all + B108 /tmp (design/portability).
- FUNCTIONAL BUG FIXED: `src/security/orchestrator.py::SecurityScanner.scan_path`
  used `root.rglob("*")`, so a single FILE target returned 0 files although the
  CLI advertises "files or directories". Now: `root.is_file()` → scan_file
  directly → ScanResult(files=1). +test `test_scan_path_single_file`.
- PERF: added idempotent indexes for the three un-indexed hot sorts —
  `idx_conversations_updated` (conversations.updated_at DESC; chat sidebar),
  `idx_council_sessions_created` (council_sessions.created_at; history),
  `idx_agent_genome_rank` (agent_genome standing/runs/name; genome panel).
  `init_schema` runs `executescript(_SCHEMA)` on every connect, so existing DBs
  pick them up automatically (CREATE INDEX IF NOT EXISTS).
- Gates after: ruff clean, mypy 95 files, check_annotations 95, `pytest --cov`
  1500 passed @ 98.78%, autopilot 186 @ 100%.
- HIGH-RISK proposals (NOT implemented — await tyba's go): MCP client/server
  (2026 de-facto tool standard), human-in-the-loop interrupt/approval gates in
  the patterns, real embeddings + vector backend (replace lexical hash
  embeddings), async runtime, OTel export/cost-budget enforcement.

## MCP — inventory (2026-10-13, READ-ONLY recon)
- **An existing MCP server lives at `src/novamind/core/mcp_server.py`** — do NOT
  build a second one from scratch. `NovaMindMCP` (JSON-RPC 2.0 over stdio,
  protocol "2024-11-05" — OUTDATED for 2026), `run_stdio_server()`,
  `MCP_VERSION` constant. It exposes the novamind `AgentFactory` (~79 tools —
  docstring says 52, stale) as code-analysis tools (DEFAULT_SCHEMA requires
  `code`). IMPORTS OK, initialize handshake OK, list_tools returns 79. ZERO
  tests (nothing in tests/ references mcp).
- Tool surfaces are FRAGMENTED across 3 layers: (1) framework
  `LocalToolExecutor` — read/list/grep only, stdlib, tested;
  (2) novamind legacy `tools.base.registry` (web/file/shell/git tools) —
  importable ONLY in the novamind layout, e.g. `git_tools.py` uses
  `core.git_manager.GitManager` (exists, imports OK); (3) autopilot SCM
  (GitHub/GitLab read adapters, 186 tests).
- The framework's REAL surface for MCP = 20 agents + security scanner +
  LocalToolExecutor + autopilot SCM. MCP plan = CONSOLIDATE/harden the existing
  server (fix protocol version/docstring/schema per-agent, add tests), add a
  framework-surface server + MCP client for agents, then a Git tool backed by
  SCM/git_manager.
- Gotcha: repo root has a legacy `tools.py` module → `import tools` from root
  resolves to it ('tools' is not a package); the framework always imports via
  `src.tools` (src on sys.path).

## MCP — Slice 3 (SHIPPED 2026-10-13) — first-class `src.mcp`
- `src/mcp/` (framework layer, stdlib-only, phone-runnable, in coverage scope):
  - `protocol.py` — wire primitives. `MCP_PROTOCOL_VERSION = "2026-07-28"` (the
    CURRENT stateless revision: no initialize handshake; version+capabilities
    ride in `_meta`; `server/discover` advertises). `SUPPORTED_PROTOCOL_VERSIONS`
    = 2026-07-28 + 4 older. Error model (`MCPError` + JSON-RPC/MCP codes incl.
    `UNSUPPORTED_PROTOCOL_VERSION=-32022`), `TextContent`, `ToolSpec`, builders
    (`text_content`/`error_content`/`jsonrpc_result`/`jsonrpc_error`/`server_meta`),
    `request_protocol_version`/`request_client_info`.
  - `server.py` — `MCPServer` (register/add_tool/`@server.tool`/remove_tool),
    `discover()`/`list_tools()`(ttlMs+cacheScope)/`call_tool()`(handler error →
    `isError` content, never a crash)/`ping()`, JSON-RPC `handle_request`
    (notifications → None), `handle_line`, `serve(instream,outstream)`,
    `run_stdio`. Legacy `initialize` still answered. `schema_from_signature` +
    `tool_from_callable` (signature→JSON-schema; extra kwargs ignored).
  - `client.py` — `InProcessClient` (wrap a live MCPServer object) + `StdioClient`
    (spawn a subprocess, line-delimited JSON-RPC, lazy start/respawn, ctx mgr) +
    `content_text` + `to_tool_schemas` (MCP tools → framework `ToolSchema`, so
    agents consume remote tools via existing machinery) + `default_server_command`.
  - `framework.py` — `build_framework_server(backend=, root=, include_agents/
    security/local_tools/git=)` exposes **30 tools**: 20 `agent_<name>`
    (EchoBackend default), `security_scan`/`security_scan_text` (confined to
    root; profiles full/secrets/dependencies/web/apk), `read_file`/`list_dir`/
    `grep` (delegating to `LocalToolExecutor`), and `git_status`/`git_log`/
    `git_branches`/`git_diff`/`git_show` (see `git_tools.py`). Heavy imports are
    lazy; `serve_framework`.
  - `git_tools.py` — read-only git inspection (`git_available`, `git_status`,
    `git_log`, `git_branches`, `git_diff`, `git_show`) via `subprocess` with a
    15s timeout and `cwd` pinned to root; the optional `path` arg is confined
    (`_safe_path`) and `limit` clamped 1..200. Reporting commands ONLY — nothing
    mutates a repo. `GitError` carries the git stderr.
  - `bridge.py` — `MCPToolExecutor`: a drop-in sibling of `LocalToolExecutor`
    (same `execute`/`run` surface + the identical bounded ReAct loop) that
    resolves `<tool-call>` markers against a live MCP server instead of local
    files. `from_server(MCPServer)` (in-process) / `from_stdio(cmd)` (subprocess)
    build it; `tool_names()`/`tool_schemas(prefix=…)` introspect; `execute()`
    never raises (client errors → `ToolOutcome(ok=False)`). **No framework file
    changed** — patterns/BaseAgent untouched (back-compat).
  - `__main__.py` — `python -m src.mcp [root]` serves the framework surface.
- Tests (all in tests/, stdlib-only → run in the phone gate): `test_mcp_protocol.py`,
  `test_mcp_server.py` (incl. stdio loop via monkeypatched sys.stdin/stdout),
  `test_mcp_client.py` (incl. a real subprocess end-to-end), `test_mcp_framework.py`,
  `test_mcp_bridge.py`, `test_mcp_git_tools.py`, `test_novamind_mcp_server.py`
  (the legacy server's first tests, 11). **144 MCP tests** in total; `--cov=src/mcp`
  = **100%** (689 stmts / 180 branches). bridge + git tests gate real git via
  `pytest.mark.skipif(which("git") is None)`.
- novamind legacy `src/novamind/core/mcp_server.py`: `MCP_VERSION` 2024-11-05 →
  **2025-11-25** (newest handshake-based revision; 2026-07-28 removed initialize),
  stale "52 agents" docstrings fixed, note added pointing to `src.mcp`.
- NOT done (next MCP step, if wanted): exposing autopilot SCM as MCP tools, and a
  novamind-layout Git tool backed by `core.git_manager`.
- Slice 3b (agents over MCP) SHIPPED 2026-10-13: `src/mcp/bridge.py`
  (`MCPToolExecutor`) + `src/mcp/git_tools.py` (read-only git) + framework
  surface 25→30. Full repo gates after: ruff clean, mypy 103 files,
  check_annotations 103, `pytest --cov` 1644 passed @ ~98.9%.
- COMMITTED 2026-10-13 as **1045b54** "feat(mcp): add read-only Git tool surface
  (5 tools, 30 total) with sandboxing + 144 MCP tests @ 100% coverage" — pushed
  to BOTH remotes (now gitlab + origin both at 1045b54; note 3a7683c security
  commit rode along to origin, which was behind at f09a41a). Working tree: only
  `reports/` + `src/novamind/.gitignore` untracked (by design — reports/ is the
  report system, not MCP; novamind/.gitignore is off-topic). No Slice 3, no main
  merge, no write tools — per tyba's mission gates.

## Current blocker (2026-10-13)
- CI + Tests are RED but NOT for code reasons: the repo is PRIVATE and the
  free account's Actions minutes / spending limit are exhausted → GitHub
  refuses to start every job ("recent account payments have failed or your
  spending limit needs to be increased", run 38321114248, all jobs fail in
  2-5s). Fix = make repo public (Actions free+unlimited; verified NO secrets
  tracked, .env gitignored + never in history) OR set a billing payment
  method. Local gates still run on the phone (`pytest --cov`, ruff, mypy).

## Decisions
- 2026-10-12: unified as nexus-core v1.0.0 (merge, coexistence layout). Both old
  repos archived after release. Framework keeps its 99% gate; novamind layer
  gated at its own historical scope (unit+observability).
- 2026-10-12: novamind deps → optional `novamind` extras in pyproject; phone
  stays stdlib-only (pip install of fastapi/pydantic/cryptography aborted by
  user — CI verifies novamind instead).
- 2026-10-12: Phase-11 files (streaming.py, checkpoint.py, toolruns.py + 2 test
  files) were UNCOMMITTED in tyb-zyv-ai — copied from the working tree here.
- Version lives in pyproject.toml AND src/__init__.py (both 1.5.0).
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
- `docs/legacy/` (commit e528b54): historical files recovered from git —
  unified_agent_v10.py (970 lines, LangGraph/LSP/MCP/A2A),
  unified_ui_v0.html (49KB ar UI), registry_v3.1_arabic.py
  (`git show bcce802:src/novamind/core/hive/factory/registry.py.old`),
  + README. Rule: never delete a file without saving it in git first.

## Sessions note
- Full session notes: vault `04 Sessions/2026-10-12 nexus-core merge*.md`.