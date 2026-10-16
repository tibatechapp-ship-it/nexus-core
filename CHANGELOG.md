# Nexus-Core Changelog

All notable changes to this project. Newest first.

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
