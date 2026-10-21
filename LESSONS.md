# LESSONS — nexus-core

## L1: Never trust "done" from an agent
Agents can hallucinate execution. Always verify with:
    git rev-list --count <base>..HEAD
    find ~ -name '<expected-file>'
    git stash list / git reflog -20
    grep -c '<expected-marker>' <expected-file>

## L2: pytest green is not CI green
`make check` is the only gate before tagging. It runs lint + mypy +
pytest + coverage. A green pytest alone is not sufficient evidence.

## L3: `assert X or True` guards nothing
Any assertion ending in `or True` (or `or <truthy-constant>`) is a
vacuous guard. Review all `assert` lines for accidental always-true
conditionals when touching regression tests.

## L4: Additive, not replacement
When wiring a new logger (e.g. request_log) into an existing path,
add it alongside the old one (_metrics.record). Do not replace —
other consumers (dashboard, maintenance) may depend on the old log.

## L5: Tag immutability
Once v*.*.* is pushed to origin + gitlab, never `git tag -f` it.
Ship a v*.*.*+1 hotfix instead.

## L6: Verify with raw output, never with summaries
Agents can produce detailed, plausible-looking summaries of work they did
NOT perform. Third hallucination observed in this session (v1.37.0 agent,
9f3a7c2 phantom commit). Rules:

1. When an agent reports "done", the ONLY acceptable proof is raw terminal
   output the human ran themselves:
     git log --oneline -1          # must show a NEW sha
     git show <sha> --stat         # must list the claimed files
     git status --short            # must be clean

2. If `git show <sha>` returns "fatal: ambiguous argument", the commit
   does NOT exist. Reject, do not negotiate.

3. If `grep -rn 'pattern' file` returns nothing, the file does not
   contain what the agent claims. Do not accept "8 files changed" without
   a matching `git diff --stat`.

4. Security findings must be re-verified by the human. A scanner file
   containing "shell=True" as a REGEX PATTERN is not a vulnerability.
   A legacy archived file is not active code.

5. When in doubt, run: `grep -rn 'def run_shell' src/ ` — if no match,
   the "fix" has nothing to fix.

## L7: Local models (qwen3:1.7b) are competent code generators, poor pytest authors
The local model generated correct assertions for the /health endpoint
(status 200, status=ok, timestamp exists), but placed them at module
level instead of inside def test_*() functions. Pytest silently skipped
them ("no tests ran"). Always wrap generated test code in explicit
test functions, then run pytest -v to confirm collection. Manual rewrap
takes 30 seconds and produces proper regression tests.

## L8: FastAPI Mount swallows every route registered after it
In nexus_agent.py, app.mount("/", StaticFiles(...)) is registered
early. Any route defined AFTER it (including @app.get("/health")) is
unreachable, returning 404 despite existing in the source. The
_ORCHESTRATOR_ROUTES tuple is the central fix: every new route must be
added there so _nexus_reorder_orchestrator_route() moves it before the
Mount. This bug lived unnoticed from v1.38.0 to v1.38.1 — only the
new regression test surfaced it.
