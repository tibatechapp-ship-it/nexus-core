# nexus-core — project memory

Unified AI Agent System: **Memory + Learning + Security + 20 Agents** — the
merge of tyb-zyv-ai (stdlib-only 20-agent framework + TUI) and novamind-core
(server-side orchestration). v1.0.0, MIT, repo
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
- Version lives in pyproject.toml AND src/__init__.py (both 1.0.0).
- Coverage badge: shields endpoint at .github/badges/coverage.json, committed
  by the badge CI job (framework coverage only).
- Adversarial suite: 92 vectors / 8 categories, HELD = pass. Stdlib-only
  invariants in tests/adversarial scan FRAMEWORK_FILES (novamind excluded by
  design). Do NOT widen to src/novamind.

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

## Release flow
1. Verify gates → commit + push main
2. `gh release create v1.0.0 --title "nexus-core v1.0.0 — Unified AI Agent System" --notes "..."`
3. Archive old repos: `gh repo archive tibatechapp-ship-it/novamind-core` +
  `gh repo archive tibatechapp-ship-it/tyb-zyv-ai` (after both have a README
  pointer to nexus-core).

## Sessions note
- Full session notes: vault `04 Sessions/2026-10-12 nexus-core merge*.md`.