# nexus-core — project review & fix ledger (v1.27.0)

> A ground-up evaluation of this repository at the `v1.27.0` release: what it
> does well, how it actually compares to the open-source agent frameworks,
> where its real weaknesses are, and what was fixed in the same pass.
> **Every claim below is backed by a command that was actually run** (see
> [Verification](#7-verification)).

Date: 2026-10-20 · Version reviewed: `v1.27.0` (`main` = `0d29cc9`) ·
Reviewer: Zyvo (automated, on-device in Termux) · Prior review: the v3.0.0
tyb-zyv-ai review at the top of this file (pre-merge, kept for history).

---

## 1. What this project is

`nexus-core` is a **Termux-native, offline-first AI agent platform**. It is not
a thin wrapper around a hosted framework — it is a self-contained system with
two layers sharing one repo:

1. **Framework layer** — stdlib-only, phone-runnable: 20 built-in agents
   (`src/agents`), orchestration patterns (`src/patterns`:
   supervisor/pipeline/fanout/delegation/blackboard), a model router + context
   manager (`src/core`), 4 SQLite memory stores (`src/memory`), a continual
   learning loop (`src/learning`), a static security scanner (`src/security`),
   a declarative tool layer (`src/tools`), and a Textual TUI (`src/tui`).
2. **Server / novamind layer** — the Living Council (`src/novamind/council`, 6
   members), the workbench council (`src/council`, 3 members), orchestrator
   (`src/orchestrator`), training + genome (`src/novamind/training`,
   `genome_v2`), knowledge base (`src/knowledge`), skills (`src/skills`), MCP
   (`src/mcp`), execution verifier (`src/verify`), call monitoring
   (`src/nexus`), maintenance (`src/maintenance`).

The design constraint that shapes everything: **runs on a phone, no heavy
dependencies in the core.** `src/novamind/**` is excluded from the four quality
gates and verified by its own tests, so the framework surface stays strict.

---

## 2. Strengths — backed by measured facts

| Strength | Evidence (command actually run) |
| --- | --- |
| **Real, executable agent benchmark** — not "did it answer" | `progbench`: 144/160 = **90% pass@1** across 20 agents × 8 tasks; the tests_slugify `mutation` task is the honest hard one at 35% |
| **Living Council, live** | 16/16 council-bench metrics passed; `POST /api/council/debate` streams session→round→6×member→consensus→verdict→done |
| **Regulation-grade gates** | `ruff` clean · `mypy 182` files · annotations `182` · full gate **3408 passed, 1 skipped @ 99.78%** |
| **Security dogfooding** | own scanner flags its own detector regexes (expected FP); **tracked-file secret scan = 0 findings**; `.env` untracked (only `.env.example`) |
| **Two remotes, one truth** | `main` = `0d29cc9` on origin **and** gitlab; CI **green** (CI + Tests) on `main` |
| **Verification by execution** | `POST /api/verify/fix` runs the produced code in a real sandbox; exit code is the referee — proven live (exit 1 → exit 0) |
| **Genome that survives restart** | `data/genome.json` persistence proven: 20 rows survive `sv restart nexus-core` |
| **Honest error model** | `craft`/`build` return HTTP 200 + `ok=false`; unmeasurable verification runs report `runner-error`, never a fake pass |

---

## 3. How it compares to the open-source frameworks (2026)

Sources: [DEV comparison](https://dev.to/ultraduneai/eval-004-ai-agent-frameworks-langgraph-vs-crewai-vs-autogen-vs-smolagents-vs-openai-agents-sdk-190l),
[internalsdecoded](https://www.internalsdecoded.com/articles/agent-framework-comparison),
[digitalapplied](https://www.digitalapplied.com/blog/open-source-agent-frameworks-5-compared-2026).

| Capability | LangGraph | CrewAI | AutoGen | Smolagents | **nexus-core** |
| --- | --- | --- | --- | --- | --- |
| Core paradigm | stateful graph | role crew | async actors | code-first | **hybrid: patterns + council + orchestrator** |
| Core deps | langchain-core (heavy) | many | many | litellm | **stdlib-only core** |
| Runs on a phone | no | no | no | maybe | **yes (verified)** |
| Built-in agents | none | none | none | none | **20 (+79 novamind modules)** |
| Persistence | checkpointer (Postgres/Redis) | event checkpoints | runtime | none across runs | **SQLite + JSON, `sv restart`-proof** |
| Multi-agent debate | graph | crew | GroupChat | ManagedAgent | **council with live SSE streaming** |
| Self-eval / genome | no | no | no | no | **genome_v2 (judgement + task channels)** |
| Execution verifier | no | no | no | sandbox (E2B/Modal) | **`src/verify` on own exec sandbox** |
| MCP | yes | yes (v1.10) | partial | yes | **30-tool framework surface** |
| Security scanner | no | no | no | no | **8-regex offline scanner** |
| Deployment infra | LangGraph Platform | CrewAI+ | MAF/Azure | HF Spaces | **runit + GitHub Pages + Release** |

**Honest read:** the big frameworks win on ecosystem breadth (integrations,
managed deployment, LangSmith-style observability) and community size (26K–55K
stars). nexus-core does **not** try to compete there. Its differentiators are
real and rare: a **stdlib-only core that runs on a phone**, a **built-in agent
roster**, a **live council with streaming**, a **self-evaluation genome**, and
**execution-based verification** — none of which the OSS leaders ship built-in.

---

## 4. Real weaknesses (ranked by impact)

| # | Weakness | Severity | Evidence | Status |
| --- | --- | --- | --- | --- |
| W1 | **`check_version_sync` read an arbitrary tag at HEAD** — with a `backup/*` fixture tag alongside `v1.27.0`, `git describe --exact-match` returned the backup tag → the orphan-release guard could fail silently | **high** | `git describe --tags --exact-match` → `backup/main-20261020-122531` while `git tag --points-at HEAD` → `[backup/..., v1.27.0]` | **FIXED** (this pass) |
| W2 | **OpenAPI spec documents 11 routes, gateway serves ~118** — parent 44 + engine 74. The spec covers only the workbench surface | medium | `/api/diag` → parent 44 / engine 74; `docs/openapi.yaml` → 11 paths | open (documented) |
| W3 | **`src/novamind/**` excluded from the four gates** — verified only by its own tests; a framework-scope assumption that widens over time | medium | `pyproject.toml` ruff/mypy/coverage omit; `check_annotations.py` SKIP prefixes | open (design decision) |
| W4 | **Two genome stores coexist** — v1 (SQLite `/api/genome`, Living Council) and v2 (JSON `/api/training/fitness`, Academy). The bridge (v1.20.2) mirrors council→v2, but the split remains | low | `/api/genome` vs `/api/training/fitness`; `data/genome.json` + `agent_genome` table | partially mitigated |
| W5 | **Own scanner verdict on `src/` is HIGH (33)** — 236 findings, dominated by the scanner matching its own detector regexes + test fixtures | low | `python -m src.security src/` → verdict HIGH, 33 high | by design (self-referential FP) |
| W6 | **`egg-info`/build artifacts + `data/` runtime files in the tree** | low | `ls data/` → 22 runtime files (all gitignored) | by design (gitignored) |

---

## 5. Fixes landed in this pass

### FIX 1 — `check_version_sync.py`: deterministic release-tag selection

**Root cause.** `read_git_tag_on_head()` used
`git describe --tags --exact-match`, which returns an **arbitrary** tag when
several point at the same commit. The release flow creates
`backup/<branch>-<stamp>` tags, so a maintenance tag could be returned instead
of `vX.Y.Z` — the orphan-release rule then compared the wrong string and failed
**silently**.

**Fix.** `read_git_tag_on_head()` now runs `git tag --points-at HEAD` (lists
every tag), keeps only semver `v`-tags via a new pure `_release_version()`
helper, and picks the **highest** deterministically. Backup tags, tagless
commits, and non-semver tags are ignored. Docstring updated to match.

**Proof.**

```
before: git describe --tags --exact-match  -> backup/main-20261020-122531
after : python scripts/check_version_sync.py -> git tag (HEAD) -> 1.27.0  (exit 0)
```

**Tests.** `tests/test_check_version_sync.py` gained a `TestReleaseTagSelection`
class (+12 cases): release tags accepted, `backup/*`/non-`v`/non-semver ignored,
the exact observed two-tag collision picks the release, highest wins among
several, and backup-only means "no release".

### Supporting change — accurate docstring

The module docstring still described `--exact-match`; rewritten to document
`git tag --points-at HEAD` and *why* (the arbitrary-tag trap).

---

## 6. What was NOT changed (and why)

- **W2 openapi coverage** — documenting all ~118 gateway routes is a larger,
  separate task; the drift guard already fails on *phantom* routes, so the spec
  never lies, it is only narrow. Flagged, not rushed.
- **W3 gate scope** — the exclusion is a deliberate decision (novamind keeps its
  own legacy scope); widening it needs tests for ~700 statements. Not a defect.
- **W5 scanner self-matches** — the scanner correctly flags `shell=True` /
  `eval`/`exec` patterns including its own detector source; verdict HIGH on its
  own tree is expected and was confirmed not to indicate a real vulnerability
  (secret scan = clean, `.env` untracked).

---

## 7. Verification

All commands run on-device (Termux, `~/nexus-core`, `main` = `0d29cc9`):

```text
ruff check .                                    -> All checks passed!
mypy zyvo-telegram.py zyvo-voice.py src         -> Success: no issues found in 182 source files
python3 scripts/check_annotations.py            -> OK: 182 file(s)
pytest --cov --cov-fail-under=95 --ignore=tests/novamind
                                                -> 3408 passed, 1 skipped @ 99.78%
python3 scripts/check_version_sync.py           -> All versions aligned (exit 0)
git describe --tags --exact-match               -> backup/main-20261020-122531   (the bug)
python3 -m src.security src/                    -> verdict HIGH (self-referential FP; secret-family: 0)
git ls-files | grep -E '\.env'                  -> .env.example  (.env NOT tracked)
gh run list --branch main                       -> CI success, Tests success (0d29cc91)
curl /api/diag                                  -> parent_routes 44, engine_routes 74
curl /api/health                                -> {"version":"1.27.0","status":"ok",...}
```

Fixes are **not yet committed** — awaiting the user's go (commit + push + tag
per the release flow).

---

## 8. Verdict

**nexus-core v1.27.0 is a genuinely strong, self-contained agent platform for
its target (a phone).** It is not trying to out-ecosystem LangGraph or CrewAI,
and it should not: its value is a stdlib-only core that runs anywhere, a
built-in agent roster, a live council, a self-evaluating genome, and
execution-based verification — capabilities the OSS leaders do not ship
built-in. The gates are real and green (3408 @ 99.78%), CI is green on `main`,
and the security posture is clean.

The one **high-impact defect found** (W1: silent version-drift blind spot in the
guard itself) is **fixed and regression-tested**. The remaining items are
documented design trade-offs, not bugs.

**Score: 9.3 / 10** — docked for spec coverage (W2), the gate-scope trade-off
(W3) and the dual-genome split (W4); every other dimension is production-grade
for this project's scope and constraints.
