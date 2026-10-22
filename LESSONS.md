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


## L9: Never delete a rare executable before confirming a replacement

`zyvo.bin` (the opencode fork binary) was deleted by hand with no backup, no
`npm`, no `pkg` cache, and no remote. It cannot be reconstructed. The replacement
was validated only *after* the deletion. **Rule:** before removing any binary
that is not obviously reproducible (installer, package manager, source build
verified to reproduce the exact artifact), copy it to a safe location, verify
the copy runs, and only then delete. In this repo the safe location is
`~/backups/<name>-<YYYYMMDD>`.

## L10: OpenCode server is a Web UI, not a REST API

`opencode-termux` starts a web interface on a local port. It does **not** expose
`/v1/chat/completions` or any JSON API an agent can call. Do not build an
`LLMBackend` around it. The sanctioned HTTP API in this project is Ollama at
`127.0.0.1:11434/api/generate`.

## L11: Only one LLM service at a time (OOM)

Running Ollama and any other local model server concurrently exhausts memory on
the phone. Android kills one (or both) with no useful log. **Rule:** before
starting an LLM service, stop any other (`pkill -f ollama` is *not* safe — see
L15; use the Termux service helper or `kill <pid>` from `pgrep -a`).
`termux-wake-lock` is required to keep the process alive when the screen locks.

## L12: Never assume an API signature — inspect it

Before calling a function from another module (especially a recently added
one), read its actual signature with `inspect.signature()` or by opening the
file. Keyword arguments, positional-only markers, defaults, and return type
must all be verified. In v1.40.0 the `generate` signature was assumed to take
positional `messages` and an optional `model`; it did — but `Message` vs `dict`
handling was wrong and invisible until inspected.

## L13: A bare `pass` is not a guard — check `result.ok`

`try: run(); except: pass` hides every failure and returns a plausible-looking
result that callers will treat as success. The check must be explicit:
`if not getattr(result, "ok", False): raise ...`. This was the root cause of the
`assert X or True` regression in v1.37.0 (see L3) and of silent agent failures
in `ResilientBackend` wrappers.

## L14: Tools may fail on the phone (OOM, kill, missing binary)

Termux on Android will kill processes without warning. Pytest, mypy, ollama,
and the TUI all compete for RAM. **Rule:** every long command runs under
`timeout N`, output is redirected to `~/<name>.log` (never `/tmp` — see L18),
and the exit code is checked explicitly. A killed command is not a bug in the
code under test.

## L15: `pkill -f <pattern>` is dangerous

`pkill -f ollama` matches any process whose command line contains "ollama" —
including the shell that typed it, an editor with the file open, and any test
runner importing the module. Prefer `pgrep -a ollama` (to list) and then
`kill <pid>` (to target). If you must use `pkill`, restrict with `-x` (exact
name) and `-u $(id -u)`.

## L16: "Preparing..." is not an error

Several Termux tools print `Preparing...`, `Installing...`, or `Setting up...`
and then sit silently for minutes before producing output. Do not `^C`. Do not
assume the process hung. Wait for the exit code (`echo $?`). `make cov` in this
repo legitimately takes ~200 seconds; `tail` on a running pipe will look frozen.

## L17: `make check` on Termux takes 3-4 minutes (cov ~198s)

`make cov` alone runs 3593 tests plus coverage plus benchmarks in ~198s. Piping
to `tail` makes it look hung. **Rule:** redirect to a file
(`make cov > ~/cov.log 2>&1; echo $?; tail -8 ~/cov.log`) and read the exit
code, never the visual silence. Confirmed in v1.40.0 → v1.40.1 verification.

## L18: `/tmp` is not writable on Termux

`> /tmp/foo.log` fails with `Permission denied` on stock Android/Termux. Use
`~/foo.log` or a path inside the project (`./foo.log`, then delete it). This is
Android's sandbox, not a config error.

## L19: Manual metrics in docs always drift

Hand-updating "N tests" or "N files" in `README.md` / `AGENTS.md` drifts on
every commit that touches the suite. Four corrections in one session still left
four conflicting numbers cited the same day. **Rule:** a number in docs must be
live-linked (badge), regenerated by CI, or deliberately vague (`3400+ tests`,
`~99%`). Never hand-fix an exact stale number. (Migrated from the old
`docs/LESSONS.md`.)

## L20: Unanchored `.gitignore` patterns hide files at every depth

`legacy/` in `.gitignore` matches `legacy/` **and** `docs/legacy/` — a new
tracked file `docs/legacy/AGENTS_HISTORY.md` was silently ignored, `git add`
did nothing, and the loss only surfaced as a `−2131 lines` diff with no
matching addition. **Rule:** anchor with `/` (`/legacy/`), add a comment, and
after creating a file in a new directory run `git check-ignore -v <path>` (must
print nothing). Same class of silent hiding: `/memory/` hid 33 MB of local
state; `--ignore=tests/novamind` hid 54 tests from the default gate. Verify
with `git status --ignored` and `pytest --co`. (Migrated from the old
`docs/LESSONS.md`.)

## L21: Read endpoints must be pure

A `GET` must not change state. In v1.30.0 the maintenance task ledger was
written both inside `generate_tasks()` and by the caller, so calling the
read/metrics path twice inflated the counts. **Fix:** the planner is pure; only
the script that performs a real mutation writes the ledger. **Test rule:** call
the GET twice and assert state-before == state-after. (Migrated from the old
`docs/LESSONS.md`.)

## L22: Never diagnose API behaviour from a screenshot

Two "bugs" reported against v1.30.0 (Arabic keys, a missing `high_pct`) were
artifacts of a machine-translated browser screenshot. The live HTTP contract had
lowercase English keys and never lacked the field. **Rule:** always read the
real contract with `curl` (or `inspect.signature`, see L12) before filing or
fixing. (Migrated from the old `docs/LESSONS.md`.)


## L23: Backfilling old releases steals the `Latest` badge

After creating releases retroactively for older tags (\`gh release create v1.38.1\`,
\`v1.39.0\`), GitHub marks the **most recently published** release as \`Latest\`,
not the highest semver. The repo suddenly advertised v1.38.1 as the current
version while v1.40.2 was the real one. **Rule:** after any backfill of releases,
re-run \`gh release edit <latest-version> --latest\` and verify with
\`gh release list\`. This applies to any tool that has an explicit "latest"
pointer separate from tag sort order.
