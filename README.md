
## Quick Start

```bash
git clone https://github.com/tibatechapp-ship-it/nexus-core.git
cd nexus-core
make check
```



# nexus-core

> **Unified AI Agent System: Memory + Learning + Security + 20 Agents**

[![CI](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/ci.yml/badge.svg)](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/ci.yml)
[![Tests](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml/badge.svg)](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/tibatechapp-ship-it/nexus-core/main/.github/badges/coverage.json)](https://github.com/tibatechapp-ship-it/nexus-core/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

**nexus-core** is the unified successor of two projects that grew together:

- **tyb-zyv-ai** — a 20-agent framework + interactive Textual TUI + persistent
  memory + continual learning + an offline security scanner. Pure Python
  **standard library only** — runs on a phone with zero installs.
- **novamind-core** — a multi-agent orchestration system ("novamind-hive"):
  security gatekeepers, sandboxed execution, RAG, observability and a FastAPI
  server layer (opt-in extras).

One repository, two layers, every feature kept:

```
src/            framework (stdlib-only, phone-safe, fully tested)
  agents/       20 built-in agents (core/planning/quality/ops)
  core/         types, LLM backend protocol, streaming, context, resilience
  patterns/     Supervisor, Pipeline (resumable), Fanout, Delegation, Blackboard
  memory/       4 SQLite stores (episodic/semantic/procedural/emotional) + RAG
  learning/     experience collector → lessons → anti-forgetting
  security/     offline static security scanner (8 agents) + CLI
  tools/        read-only tool execution (ReAct loop, confined root)
  tui/          Textual terminal UI (screens, tool traces, security)
  mcp/          Model Context Protocol server/client + agent bridge (30 tools)
  council/      Council workbench engine (3 members) + Craft code generation
  novamind/     former novamind package (opt-in `novamind` extras)
hyper_agent.py  Hyper-Agent 2.0 — autonomous coding agent (BUG-1..9, JSONL logs)
connectors/     BYOK LLM adapters (openai/anthropic/groq/ollama/deepseek/gemini)
hyper_app/      Hyper-Agent API surface (POST /api/agent/start)
tests/          framework suite (3400+ tests @ ~99%) + tests/novamind/ (opt-in)
main.py         Council workbench server (FastAPI) + index.html console
zyvo-*.py       standalone Telegram + voice assistants
docs/           framework + novamind documentation
```

## Quality gates

One command defines "green" (`make check` → ruff, mypy, annotation check,
tests + coverage). The **framework surface** (the stdlib-only core + the zyvo
scripts) is gated; the opt-in novamind + workbench/web layers are excluded from
those gates and verified by their own tests. The same scope is applied
consistently in `pyproject.toml`, `scripts/check_annotations.py` and the
coverage config.

```bash
make check     # ruff check .  +  mypy  +  annotations  +  3400+ tests @ ~99%
```

An adversarial red-team suite (`tests/adversarial`, 92 vectors / 8 categories)
guards the framework — including a live supply-chain invariant that fails on any
import not declared in `pyproject.toml`.

## Install

```bash
# The framework itself needs nothing (stdlib only)
python -m pip install -e ".[dev]"          # test tooling
python -m pip install -e ".[voice,tui]"    # voice assistant + TUI extras
python -m pip install -e ".[novamind]"     # former novamind server layer
```

## Run

```bash
python -c "from src.core.backend import EchoBackend; from src.tui.app import run_app; run_app(backend=EchoBackend())"   # 20-agent TUI
python zyvo-telegram.py
python zyvo-voice.py
python -m src.security . --fail-on high   # offline security scan
```

## Chat server + web UI (v1.5)

The FastAPI layer (`unified_agent.py`) serves a ChatGPT-style web UI plus a
small JSON API. v1.5 moves conversation history server-side into SQLite,
adds a request "Time Machine", and polishes the chat surface.

```bash
python -m pip install -e ".[novamind]"
PYTHONPATH=src/novamind:src:. python unified_agent.py   # http://localhost:8000
```

- **Persistence** — `data/sessions.db` (stdlib `sqlite3`, WAL). Conversations
  and messages live in the DB, not the browser; the UI migrates old
  `localStorage` on first boot.
- **Time Machine** — every request is logged (message, response, agent,
  latency, status, planner output) under `/api/traces`, with replay and
  JSON/Markdown export.
- **Chat polish** — Markdown tables & images, copy/regenerate/edit, pin,
  inline rename, and full conversation export/import.
- **API** — `/api/chat` (SSE stream), `/api/conversations[...]`,
  `/api/traces[...]`, `/api/export/conversations`, `/api/db/stats`.

## Council workbench + Craft (v1.12)

A focused, self-contained Council console (`main.py` + `index.html`) — separate
from the v2.0 "Living Council" below. Three members (Profiler / Analyst /
Critic) deliberate a question in Arabic or English and return a verdict, a
confidence score and a one-line recommendation, streamed live over SSE.

```bash
PYTHONPATH=src:. python main.py      # http://127.0.0.1:8000
```

**Craft mode** (`POST /api/craft`, console: `/craft <desc> [review]`) turns a
free-text brief into **real working code** — no prior debate needed:

- the model returns strict JSON `[{"path","content"}]`; every path is confined
  (`..`/absolute rejected) and extensions are allow-listed;
- every generated `.py` is run through `py_compile` — the response carries a
  `proof` block, and a render error means `proof.ok=false` (no silent success);
- with `review`, the Council then votes on the generated artifact itself.

The console also adds **voice**: `/session` starts a hands-free conversation
(Web Speech `ar-SA` → deliberate → spoken verdict, say "توقف" to end), plus TTS,
generated SFX, search, share and transcript export. The web app is installable
(PWA) with a service worker that never caches `/api/*` (so streaming stays live).

## The Living Council (v2.0 — المجلس الحيّ)

Three to five specialised agents debate a topic **live** (streamed to the UI),
a chief synthesises a **verdict**, and each member's *standing* rises or falls
by how well it agreed with the final decision.

- **Engine** — `src/novamind/council/council.py`: 5 members (analyst, critic,
  visionary, pragmatist, expert) debate over 1–5 rounds; per-round consensus
  (largest agreeing fraction by token-Jaccard); early stop at ≥ 0.8.
- **Works offline** — with no live provider it runs a deterministic local
  simulation, so tests and the phone gate never need the network. A live
  failure flips the run to offline for 60 s (self-healing); each call is
  bounded so a hung provider can't stall a debate.
- **API** — `POST /api/council/stream` (SSE: `session`, `round`,
  `member_start`, `member_message`, `consensus`, `verdict`, `done`),
  `POST /api/council/debate`, `GET /api/council/sessions`,
  `GET|DELETE /api/council/sessions/{id}`.
- **UI** — the ⚖️ topbar button opens the council panel: topic + rounds, live
  member bubbles, consensus bars, verdict card with influence, and history.

## Agent Genome (v2.0 — جينوم الوكلاء)

Every agent has a permanent genome: a persona, a lineage (generation / parent),
and lifetime performance (runs, successes, latency, verdict alignment). The
council feeds each member's outcome back into its genome, so **standing rises
and falls across sessions** — the strong get promoted, the weak go to
probation and can be re-trained.

- **Engine** — `src/novamind/genome/`: pure `scoring.py` (success rate,
  consensus, speed → a weighted 0-1 standing; `promoted` / `active` /
  `probation`) plus a `Genome` manager over the SQLite `agent_genome` +
  `genome_events` tables.
- **Learning loop** — after every debate the council records each member's
  verdict alignment, latency and consensus; the genome recomputes standing and
  keeps an append-only timeline (born / outcome / council / edit / reset).
- **API** — `GET /api/genome` (ranked agents), `GET /api/genome/{id}`
  (detail + timeline), `PATCH /api/genome/{id}` (edit persona), `POST
  /api/genome/{id}/reset` (re-train), `GET /api/genome/export`, `POST
  /api/genome/import`.
- **UI** — the 🧬 topbar button opens the genome panel: ranked agent cards with
  🥇🥈🥉 badges, standing bars, status pills; click one for stats, its editable
  persona, re-train, and its evolution timeline.

## PWA + offline (v2.0)

The web UI is an installable progressive web app (Arabic, RTL) that keeps
working when the network drops.

- **Installable** — `web/manifest.json` (name, RTL, theme, shortcuts) +
  generated icons (192 / 512 / maskable-512, drawn by
  `stdlib`-only PNG writer) + a "تثبيت التطبيق" button when the browser offers
  install (`.web/` serves them all at `/manifest.json`, `/sw.js`,
  `/icon-*.png`, `/offline.html`).
- **Service worker** — `web/sw.js` precaches the app shell, is network-first
  for GET `/api/*` with a cache fallback, and serves a friendly offline page
  for navigations.
- **Offline queue** — when you send a message while offline it is queued in
  IndexedDB (badge `⏳ n` in the composer), and replayed automatically the
   moment the connection returns.

## Hyper-Agent 2.0 — autonomous coding agent (BYOK)

A self-driving coding loop: the LLM proposes one JSON action per turn
(`CODE` / `TEST` / `DONE` / `ERROR`), the harness executes it in a subprocess
sandbox (CPU / FSIZE / NPROC rlimits — no `RLIMIT_AS`, so it also runs on
Android), and `verify_goal` gates the exit. Every iteration is appended to a
JSONL log (`NEXUS_HYPER_LOG`, else `LOG_PATH`) so a whole cycle can be
replayed line by line.

- **`hyper_agent.py`** — the loop itself. The nine known failure modes
  (BUG-1..9) are designed out from birth: history is *replaced*, not
  appended (BUG-1); Ollama is capped with `num_predict: 4000` (BUG-2);
  a stall detector ends a frozen run (BUG-3); results never leak
  `raw_result` (BUG-4); `last_parse_error` is fed back to the model so it
  can correct its JSON (BUG-5); children run under `sys.executable`
  (BUG-7); `verify_goal` must pass before `DONE` is accepted (BUG-8).
- **`connectors/`** — bring-your-own-key LLM adapters behind one contract
  (`{"ok": bool, "reply"|"error": str}`): `openai`, `anthropic`, `groq`,
  `ollama`, `deepseek`, `gemini`. `connectors.registry.create_connector`
  resolves by name; an unknown provider raises `ValueError`. Keys come from
  the usual env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GROQ_API_KEY_1`, `OLLAMA_API_KEY`, …).
- **`hyper_app/`** — the API surface: `POST /api/agent/start`
  (`goal`, `max_iterations` clamped 1–20, `user_config` defaulting to
  `{"provider": "ollama"}`) plus `hyper_app/services/llm_factory.py`, the
  BYOK factory over the connector registry.
- **Tests** — `tests/test_hyper_agent.py` + `tests/test_byok_integration.py`
  (41 hermetic tests, stub LLM, no network). Coverage: `hyper_agent.py`
  99%, `src/learning` 100%.

```bash
# run the loop's own tests
PYTHONPATH=.:src python3 -m pytest tests/test_hyper_agent.py tests/test_byok_integration.py -q

# drive one goal through the API (needs a configured provider key)
curl -X POST http://127.0.0.1:8000/api/agent/start \
  -H 'Content-Type: application/json' \
  -d '{"goal": "write a fibonacci function with tests", "max_iterations": 5}'
```

## Verify before shipping (must all pass)

```bash
make check         # ruff check .  +  mypy  +  annotations  +  tests/coverage
```

Equivalently, run the gates by hand:

```bash
ruff check .
mypy zyvo-telegram.py zyvo-voice.py src
python scripts/check_annotations.py        # every function type-annotated
python -m pytest --cov --cov-fail-under=95 --ignore=tests/novamind
```

The novamind layer's suite needs the `novamind` extras and runs in CI
(`tests/novamind` — skipped automatically when the extras are absent).

## LICENSE

MIT — see [LICENSE](LICENSE).