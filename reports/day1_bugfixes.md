# Hyper-Agent 2.0 — Day 1 delivery report (BUG-1..9 + BYOK + observability)

Repo: `~/nexus-core-private` (no commits made — everything below is untracked/
modified in the working tree, awaiting your review).
Date: 2026-10-18. Session note: vault `04 Sessions/20261018-hyper-agent-2.0-build-day1.md`.

## 1. Fixed (designed in from birth — fresh build, not patched in)

The old codebase never existed here (stale premise), so every fix is the
default shape of the new code:

| BUG | Where | What |
|-----|-------|------|
| BUG-1 history bloat | `hyper_agent.py:88` (`history_tail`, docstring :23) | prune **replaces** `state["history"]` with the tail — never appends a duplicate |
| BUG-2 Ollama truncation | `connectors/ollama.py:11` | `"num_predict": 4000` baked into the request options |
| BUG-3 silent stall | `hyper_agent.py:99-112` `detect_stall()` | 3 identical non-terminal actions → `status="stalled"`; DONE/ERROR never count |
| BUG-4 raw_result leak | `hyper_agent.py:23` + history writer | stored history keeps only the parsed view, never the raw provider payload |
| BUG-5 loop on bad JSON | `hyper_agent.py:346,357` | `last_parse_error` counter fed back into the next prompt so the model can correct |
| BUG-6 Android sandbox | `hyper_agent.py:121-147,194` `_make_limits()` | `preexec_fn` with `RLIMIT_CPU/FSIZE/NPROC` only — **no RLIMIT_AS** (Android kills it); FSIZE = `MAX_FSIZE` (5 MB, `:49`) |
| BUG-7 wrong interpreter | `hyper_agent.py:176-177,227-231` | children run `sys.executable`, not bare `"python3"` |
| BUG-8 fake success | `hyper_agent.py:257-286` `verify_goal()` | DONE is gated on goal-token evidence → `status="verify_fail"` when unmet |
| BUG-9 wrong delivery names | `README.md:35-38,54,186-220` | documented the real `_`-spelled filenames (`hyper_agent.py`, `tests/test_hyper_agent.py`, …) — no `-` names anywhere |

## 2. Added beyond the report

- **`connectors/`** (9 files): one `BaseConnector` contract
  (`{"ok": bool, "reply"|"error": str}`, `connectors/base.py:7-10`) + 6 BYOK
  providers (openai `gpt-4o-mini`, anthropic `claude-3-5-haiku-latest`,
  groq `llama-3.3-70b-versatile`, ollama `qwen2.5-coder:7b-instruct-q4_K_M`,
  deepseek `deepseek-chat`, gemini `gemini-2.0-flash-exp`; timeouts 60 s /
  120 s ollama). `connectors/registry.py:22` → unknown id raises
  `ValueError("Unsupported provider: …")`.
- **`hyper_app/`**: `services/llm_factory.py` (`DEFAULT_PROVIDER="ollama"`
  :26, `create_llm_client_from_request` :30, no import-time env reads) +
  `routers/agent.py` (`POST /api/agent/start`, `max_iterations` ge=1 le=20
  :19, `user_config` default `{"provider":"ollama"}` :29).
- **JSONL cycle log**: `_append_log` (`hyper_agent.py:76`) — one record per
  iteration, `NEXUS_HYPER_LOG` env override, directory auto-created (:83-84).
- **README Hyper-Agent chapter** (`README.md:186-220`) + layout/gate updates
  (counts refreshed to the verified 3105 tests / 167 mypy files).
- **`_fold_system_into_prompt`** (`hyper_agent.py:114`): Ollama connector has
  no system channel → system text prepended instead of dropped.
- Fence-aware JSON extraction in `_parse_action` (`hyper_agent.py:287-302`).

## 3. Tests + gates (re-verified fresh, this session)

- `tests/test_hyper_agent.py` (33 tests) + `tests/test_byok_integration.py`
  (8) — hermetic `_StubLLM`, no network; one test-line fix: line 447 now
  asserts `RLIMIT_FSIZE → MAX_FSIZE` (the test was wrong, production right).
- Full gate: `PYTHONPATH=.:src python3 -m pytest tests/ -q --ignore=tests/novamind --cov --cov-fail-under=95`
  → **3105 passed, 1 skipped** (ed25519 device-only) **@ 145 s**.
- `ruff check` (src/learning + connectors + hyper_app + hyper_agent + tests)
  → clean. `mypy zyvo-telegram.py zyvo-voice.py src` → **167 files clean**.
  `scripts/check_annotations.py` → **167 files OK**.
- Coverage: **`hyper_agent.py` 99%** (212 stmts / 58 branches; only partial
  branch `451→454`, the defensive `if` on a killed process) · **`src/learning`
  100%** (tools.py 98% = 4 pre-existing lines). DoD (≥95 % both) met.

## 4. Deliberately skipped (with reason)

- **`RLIMIT_AS` in the sandbox** — Android's linker kills any process that
  sets it; CPU/FSIZE/NPROC is the proven Termux-safe trio (same as
  `tools/exec_sandbox.py`).
- **Real-LLM smoke of the full loop** — needs a live provider key on the
  device; factory + registry verified by import-probes instead (unknown
  provider → ValueError, ollama → expected model). Run one live goal when you
  supply a key: `curl -X POST :8000/api/agent/start -d '{"goal":"…"}'`.
- **Commit** — none made, per your review rule. `README.md` is the only
  *modified* tracked file; everything else is untracked.

## 5. Future work (Day 2+)

- Wire `execute_code` (`src/learning/tools.py:328`) to the sandbox runner.
- React-agent loop (plan → act → observe) on top of `autonomous_workflow_hyper`.
- JSONL replay viewer (read a cycle back, step by step).
- Orchestrator CLASSIFY decides which agents run (Day 3 of your plan).
- Optional: persist cycles into SQLite (session store) instead of file-only.

## 6. How to run it

```bash
cd ~/nexus-core-private
PYTHONPATH=.:src python3 -m pytest tests/test_hyper_agent.py tests/test_byok_integration.py -q
# API (needs a provider key in env):
PYTHONPATH=.:src python3 -c "from hyper_app.services.llm_factory import create_llm_client_from_request; print(create_llm_client_from_request())"
```
