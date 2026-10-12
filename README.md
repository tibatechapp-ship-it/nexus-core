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
  memory/       4 SQLite stores (episodic/semantic/procedural/emotional)
  learning/     experience collector → lessons → anti-forgetting
  security/     offline static security scanner (8 agents) + CLI
  tools/        read-only tool execution (ReAct loop, confined root)
  tui/          Textual terminal UI (screens, tool traces, security)
  novamind/     former novamind package (opt-in `novamind` extras)
tests/          framework suite (1218 tests @ 99%) + tests/novamind/ (opt-in)
zyvo-*.py       standalone Telegram + voice assistants
docs/           framework + novamind documentation
```

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

## Verify before shipping (must all pass)

```bash
ruff check .
mypy zyvo-telegram.py zyvo-voice.py src
python scripts/check_annotations.py        # every function type-annotated
python -m pytest --cov                     # 1218 tests, coverage floor 95%
```

The novamind layer's suite needs the `novamind` extras and runs in CI
(`tests/novamind` — skipped automatically when the extras are absent).

## LICENSE

MIT — see [LICENSE](LICENSE).