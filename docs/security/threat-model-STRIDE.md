# STRIDE Threat Model — nexus-core

**Scope:** the unified gateway (`nexus_agent.py`), the framework layer
(`src/{agents,core,patterns,memory,learning,security,tools,tui}`), the workbench
council (`src/council`), the novamind layer (`src/novamind`), the training /
genome stack (`src/novamind/training`, `src/novamind/genome_v2.py`) and the
maintenance layer (`src/maintenance`).

**Method:** Microsoft STRIDE, six categories — Spoofing, Tampering, Repudiation,
Information Disclosure, Denial of Service, Elevation of Privilege. Each category
lists the assets at risk, the trust boundaries, the concrete threats, and the
control — mapped to an executable PoC in `tests/security/stride/`.

**Evidence rule:** every control below is either (a) a passing PoC vector in
`tests/security/stride/`, or (b) a finding with a fix and a regression test, or
(c) explicitly an *accepted, documented gap*. No claim here is unverified.

---

## 1. System model

### 1.1 Assets

| # | Asset | Where | Why it matters |
|---|-------|-------|----------------|
| A1 | Provider API keys (Groq `GROQ_API_KEY_1..20`, ZAI `ZAI_API_KEY_1..13`, OLLAMA, …) | `.env` (root, gitignored) | Billing + account takeover |
| A2 | The gateway auth token `NEXUS_AUTH_TOKEN` | runit env dir | Gates every mutating route |
| A3 | The workspace filesystem (repo tree) | `<repo>/` | Source, `.env`, DBs |
| A4 | The genome / fitness state | `data/genome.json` | Agent reputation, self-evolution |
| A5 | The training certificates + runs | `data/training.db` | Provenance of agent trust |
| A6 | The audit + task ledgers | `data/audit.jsonl`, `data/task_log.jsonl`, `data/metrics.json` | Non-repudiation |
| A7 | The LLM budget | provider accounts behind the keys | Cost/availability |
| A8 | The council verdicts | debate SSE stream + `data/council_trace.jsonl` | Decision integrity |

### 1.2 Trust boundaries

```
  [anonymous caller]──HTTP──▶┌──────────────────────────────┐
                             │  AccessGuard middleware       │  B1: auth/rate/audit
                             │  (mutating methods only)      │
                             └───────────────┬──────────────┘
                                             │
                   ┌─────────────────────────┼──────────────────────────┐
                   ▼                         ▼                          ▼
            read routes               mutating routes             engine catch-all
        (/api/status,/api/diag)   (/api/chat, /api/genome/*,    (unified_agent app)
                   │              /api/orchestrator/*, …)              │
                   │                         │                          │
                   ▼                         ▼                          ▼
           ┌──────────────────────────────────────────────────────────────┐
           │  LocalToolExecutor (read/list/grep)   B2: workspace root      │
           │  exec_sandbox (run snippet)           B3: temp cwd           │
           │  builder._safe_rel_path (craft write) B4: build root         │
           └──────────────────────────────────────────────────────────────┘
                   │
                   ▼
            filesystem, .env, data/*.db, data/*.json
```

* **B1 — gateway middleware.** Everything a client sends crosses here. Only
  POST/PUT/PATCH/DELETE are gated; GETs are open by design (dashboard reads).
* **B2 — tool sandbox root.** Model-emitted tool calls resolve under a root and
  must not escape it *or* read in-root secret stores.
* **B3 — exec sandbox cwd.** Generated code runs in a temporary directory with
  resource limits.
* **B4 — craft build root.** LLM-authored files are written under a validated
  relative path.

### 1.3 Data-flow assumptions

* The gateway binds **127.0.0.1** by default — no public exposure unless the
  operator changes it. This *reduces* but does not remove the need for auth
  (a local process, a browser on the phone, or a mis-bound deploy can reach it).
* Provider keys are read from env **at call time** (not at import), so a leaked
  process env is the exposure vector, not the source tree.
* Runtime state lives in `data/` (gitignored) — never in `memory/` (a CI guard
  fails a test that writes there).

---

## 2. Spoofing (S)

**Goal of the attacker:** act as another principal — a legitimate client, or
another agent.

| ID | Threat | Control | PoC |
|----|--------|---------|-----|
| S1 | Timing side-channel on the auth token (naïve `==` leaks length/prefix) | `hmac.compare_digest` constant-time compare | `test_spoofing.py::test_s1_token_compared_in_constant_time` |
| S2 | Empty/blank token accepted (`"" == ""`) | A blank token → auth disabled, never "match anything" | `…::test_s2_blank_token_is_never_a_match` |
| S3 | Header-spelling confusion (`X-Auth-Token` vs `x-auth-token`, smuggling) | One canonical header, case-normalised by the ASGI layer | `…::test_s3_header_spelling_is_exact` |
| S4 | Forge an `agent_id` to impersonate a roster agent | `get_manifest()` raises `KeyError` on an unknown id; agents are looked up by exact key | `…::test_s4_unknown_agent_id_is_not_a_roster_key` |
| S5 | Spoof a client identity to defeat the rate limiter via `X-Forwarded-For` | The limiter keys on the real client, not a spoofable header | `…::test_s5_rate_limit_does_not_trust_forwarded_for` |

**Residual:** on a shared, unauthenticated deployment (token unset) any caller
is "the" caller — by design the operator must set `NEXUS_AUTH_TOKEN` before
exposing the gateway. Documented gap: see §8.

---

## 3. Tampering (T)

**Goal:** modify data or code the attacker does not own.

| ID | Threat | Control | PoC |
|----|--------|---------|-----|
| T1 | Path traversal in a tool-read (`../../etc/passwd`) | `_resolve` confines to the workspace root | `test_tampering.py::test_t1_traversal_is_confined` |
| T2 | Craft-mode write escaping the build root | `builder._safe_rel_path` rejects absolute/`..` paths | `…::test_t2_builder_write_gate` |
| **T3** | **`POST /api/genome/import` with a non-list / non-dict payload raises `AttributeError` → 500 and can corrupt import state** | **FIXED:** the import boundary validates shape and tolerates junk (`_as_int`/`_as_float` coercion, skip non-dict rows) | `…::test_t3_genome_import_tolerates_hostile_payload` |
| T4 | A GET mutates state (ledger inflation) | Read endpoints are pure — proven by double-call invariance | `…::test_t4_reads_are_pure` |
| T5 | Exec sandbox writes/modifies host files | Sandbox runs in a temp cwd with FSIZE/CPU/NPROC limits | `…::test_t5_exec_sandbox_is_confined` |

**T3 detail (finding):** `SessionStore.genome_import` iterated its argument and
called `a.get(...)` on each element. A string (`"not-a-list"`) or a list of
non-dicts therefore raised `AttributeError: 'str' object has no attribute 'get'`
→ HTTP 500. A hostile caller could repeat this to produce a 500 storm (also a
DoS vector, hence it appears under both T and D).

**Fix:** at the `genome_import` boundary — reject a non-list with an empty
import; skip non-dict rows; coerce every numeric field through `_as_int` /
`_as_float` so a bad value never raises. Regression:
`tests/security/stride/test_tampering.py::test_t3_…` and
`tests/security/stride/test_dos.py::test_d2_…`.

---

## 4. Repudiation (R)

**Goal:** perform an action then deny it, or disown a verdict.

| ID | Threat | Control | PoC |
|----|--------|---------|-----|
| R1 | A mutating call leaves no attributable record | When `NEXUS_AUDIT_LOG` is set, one JSON line per call with ts/event/method/path/client/status/allowed | `test_repudiation.py::test_r1_audit_records_attributable_rows` |
| R2 | Operator believes everything is logged while audit is silently OFF | The default is explicit (`audit.enabled == False`, surfaced in `/api/status`) | `…::test_r2_audit_off_is_documented_not_silent_success` |
| R3 | The audit log itself leaks the token (audit becomes an exfiltration channel) | The credential is never written to the log | `…::test_r3_audit_never_records_the_token` |
| R4 | A council member disowns its vote | `judgement_stances` reduces the debate to per-member stances | `…::test_r4_council_vote_is_traceable` |

**Accepted gap (R):** audit is OFF by default; the honest posture is "no audit
unless the operator opts in" — documented, with the config surfaced so the state
is observable rather than assumed. See §8.

---

## 5. Information Disclosure (I)

**Goal:** read data the attacker should not see.

| ID | Threat | Control | PoC |
|----|--------|---------|-----|
| **I1** | **`GET /api/diag` (unauthenticated read) discloses the absolute server path + raw `sys.path`** | **FIXED:** `loaded_from` is now a bare filename; `sys.path` is reported as an entry **count** only | `test_info_disclosure.py::test_i1_diag_does_not_leak_absolute_paths` |
| I2 | An error path echoes an API key to the caller | The router never interpolates a key into an error string (static proof) | `…::test_i2_error_paths_do_not_echo_secrets` |
| I3 | The secret scanner misses a real token | The secrets agent flags AWS + GitHub literals as HIGH | `…::test_i3_secret_scanner_detects_realistic_tokens` |
| **I4** | **The confined tool executor reads `.env` (and any in-root secret store)** | **FIXED:** a credential deny-list in `_resolve` + `_walk_text_files` blocks `.env*`, `*pem/key/p12/pfx/keystore`, `id_rsa`, `credentials*`, `secrets.*`, `.netrc`, `.git-credentials` | `…::test_i4_no_tracked_secret_files` |
| I5 | `/api/status` echoes the guard config including the token | `stats()` returns auth/header/rate/window/audit — never the token value | `…::test_i5_status_guard_stats_hide_the_token` |

**I1 detail (finding):** `/api/diag` returned
`loaded_from: <absolute repo path>` and `sys_path_head: [...]` to any anonymous
GET. That is a ready-made reconnaissance package (install root, interpreter
layout). **Fix:** return the filename and a path-entry count; the route
inventory stays (it is already public via the OpenAPI spec) but the filesystem
layout does not.

**I4 detail (finding):** `LocalToolExecutor.execute(read, path=".env")`
**succeeded**, returning the live `.env` — including `OLLAMA_API_KEY=…`. Root
confinement was correct but incomplete: a secret *inside* the root is still a
secret. **Fix:** `is_sensitive_file()` is consulted in `_resolve` (covers `read`
and `list`) and in `_walk_text_files` (covers `grep`). `.env.example` is
deliberately allowed (it documents variable **names**, never values).

**Verified:** the repo tracks no env file except `.env.example`
(`git ls-files`), and the executor now refuses `.env`, `secrets.json`, `id_rsa`,
`cert.pem`.

---

## 6. Denial of Service (D)

**Goal:** exhaust a resource so the service stops serving.

| ID | Threat | Control | PoC |
|----|--------|---------|-----|
| D1 | Flood a mutating route → burns LLM keys / saturates the phone | The rate limiter caps a burst (fixed window) | `test_dos.py::test_d1_rate_limiter_bounds_a_burst` |
| D2 | A hostile import payload raises → 500 storm (shared root with T3) | FIXED at the boundary (tolerant import) | `…::test_d2_hostile_genome_import_does_not_crash` |
| D3 | Ask the task generator for an unbounded batch | `generate_tasks` clamps to `MAX_LIMIT` (**10**) | `…::test_d3_task_generator_clamps_batch_size` |
| D4 | A pathological (1 MB) input hangs a pure parser | `risk.classify` completes well under 2 s on 1 MB | `…::test_d4_pathological_input_does_not_hang` |
| D5 | Denied calls accumulate unbounded in memory | The rate-limit window is fixed-size; the audit log is bounded (rotated on disk) | `…::test_d5_guard_records_rejections_without_growth` |

**Accepted gap (D):** there is **no global request-body size cap** at the ASGI
layer — a very large body is buffered before a route sees it. Uvicorn/Starlette
do not impose one by default. Mitigations today: loopback-only bind + rate limit
(when enabled) + per-route caps. A body-size middleware is recommended for v1.33
(see §8, W-D1).

---

## 7. Elevation of Privilege (E)

**Goal:** gain rights you were not granted.

| ID | Threat | Control | PoC |
|----|--------|---------|-----|
| E1 | Traverse out of the tool sandbox to read host files | `_resolve` confines to root (and now denies secrets) | `test_elevation.py::test_e1_tool_executor_traversal_is_denied` |
| E2 | Call a tool outside the allow-list (`write`/`shell`/`exec`) | Only `SAFE_TOOL_NAMES = {read, list, grep}` run | `…::test_e2_unknown_tool_is_refused` |
| E3 | Craft a path that writes anywhere on disk | `_safe_rel_path` rejects escapes | `…::test_e3_builder_write_gate_rejects_escape` |
| E4 | Hit a mutating verb the guard forgot to gate | POST/PUT/PATCH/DELETE are all gated; GET is not | `…::test_e4_guard_gates_every_mutating_method` |
| E5 | Run code in the sandbox that reads the host | The sandbox uses a temporary cwd (static proof) | `…::test_e5_exec_sandbox_confines_cwd` |

---

## 8. Findings summary, fixes, and accepted gaps

### 8.1 Fixed in this audit

| ID | Severity | Finding | Fix | Regression |
|----|----------|---------|-----|------------|
| **I4** | **HIGH** | Confined tool executor read `.env` (live provider keys) | Credential deny-list in `_resolve` + `_walk_text_files`; `is_sensitive_file()` | SH-01, SH-02 |
| **T3/D2** | **HIGH** | `genome_import` raised `AttributeError`/`ValueError` on hostile input → 500 | Shape-validation + tolerant `_as_int`/`_as_float` at the boundary | T3, D2 |
| **I1** | **MEDIUM** | `/api/diag` disclosed absolute path + raw `sys.path` | Filename only + path-entry count | I1 |

### 8.2 Accepted, documented gaps (not fixed — deliberate)

| ID | Gap | Rationale | Recommended follow-up |
|----|-----|-----------|----------------------|
| W-R1 | Audit is OFF by default | Zero-config local use; enabling it requires an operator decision (path + retention) | Document the opt-in in `docs/api.md` (done) |
| W-D1 | No global request-body size cap | Requires a middleware touching every route; risk/benefit deferred | Add a `Content-Length` guard middleware in v1.33 |
| W-S1 | A gateway with no `NEXUS_AUTH_TOKEN` accepts any caller | Local-first design; the bind is loopback | Keep loopback default; warn loudly if bound to a public interface without a token |

### 8.3 Non-findings investigated and cleared

* `AccessGuard.stats()` never carries the token (I5 holds).
* The secrets scanner detects AWS + GitHub literals (I3 holds).
* No env file is git-tracked except `.env.example` (I4 tracked-file half holds).
* `judgement_stances` attributes every member's vote (R4 holds).
* Only `{read, list, grep}` execute in-framework (E2 holds).
* The rate limiter does not trust `X-Forwarded-For` (S5 holds).

---

## 9. Verification

Reproduce the whole PoC suite:

```bash
python -m pytest tests/security/stride/ -q
```

Expected: **29 passed**, 0 broken, every category at 100% resilience.

Full quality gate:

```bash
make check        # ruff · mypy · annotations · pytest --cov (floor)
```

The suite is written as *finding-detectors*: each vector states the exploit and
fails if the boundary regresses — it is not a rubber stamp.
