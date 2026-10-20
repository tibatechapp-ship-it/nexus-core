# Agent tools

The agent tool library lives in `src/learning/tools.py`. It exposes **seven
tools** behind one never-raising entry point, `safe_execute`, so an agent
(notably the ReAct loop in `src/learning/react_agent.py`) can call any of them
without a tool failure ever crashing a run.

## The seven tools

| Tool | What it does | Key settings |
|------|--------------|--------------|
| `search_web` | Bounded web search; returns up to N hits `{title, url, snippet}`. An outage returns `[]`. | `max_results` (≤ 10) |
| `read_file` | Reads a UTF-8 text file **confined to `allowed_roots`** (traversal + symlink escapes neutralised, 256 KB cap). | `allowed_roots` |
| `get_current_time` | Current time as ISO-8601 (local) + unix seconds. Injectable clock. | — |
| `query_memory` | Recalls past interactions by keyword from the Phase-1 `InteractionStore`. | `limit` (≤ 20) |
| `execute_code` | Runs code in the subprocess sandbox (`tools/exec_sandbox.py`) under a strict timeout; stdout/stderr capped at 10 KB. | `timeout` (≤ 10 s) |
| `consensus` | Several agents answer a question; one synthesizer merges them, plus an `agreement` score (mean pairwise token-Jaccard) and a `strong` flag. | `agents` (≥ 2) |
| `download_file` | Downloads a file with `aria2c` (resume-capable). **SSRF-protected**: loopback, private and reserved hosts and non-HTTP schemes are refused before any network call. | `max_file_size` |

Every call returns a `ToolResult(ok, tool, value / error, explain)`. The
`explain` line is the Arabic "why did this tool run" string the UI streams
(`explain_event` builds the SSE wire shape).

## How automatic routing works

The ReAct loop does **not** hand the model a tool menu. The model writes a
thought; `react_agent.parse_action` regex-finds the first `tool_name(...)` in
that text (bracket-matched so nested parens stay whole), splits the arguments on
top-level commas, and calls the tool through `safe_execute`. The resulting
observation is appended to the transcript for the next thought.

```
Thought: the user wants a file
download_file("https://example.com/a.zip")   →  observation {ok, value/error}
Thought: …
Answer: …
```

A thought with **no** recognised tool call becomes the final answer. `max_steps`
(default 10) bounds a runaway loop.

## Adding a new tool — three places

A new tool must be registered in **three** places, or it will not be reachable
or configurable:

1. **`_REGISTRY`** in `src/learning/tools.py` — map the name to
   `(callable, detail_extractor)`. The detail extractor turns the call's args
   into the human-readable `explain` snippet.
2. **`default_config()`** in the same file — add an entry under `tools` with at
   least `{"enabled": True}` plus any caps the tool reads.
3. **`tools_config.json`** (repo root) — mirror the same entry so the shipped
   config matches the defaults. `load_tools_config` reads this file, and
   `NEXUS_TOOLS_CONFIG` can point at a different one.

If the tool needs a bounded argument (a result count, a timeout, allowed roots),
read it from the per-tool settings inside `safe_execute` — follow the existing
`if tool_name == …` branches.

Finally, add a smoke test in `tests/test_tools_integration.py` and, if the tool
is agent-facing, a routing assertion in `tests/test_react_agent_routing.py`.

## Enable / disable a tool

Edit `tools_config.json` (or the file named by `NEXUS_TOOLS_CONFIG`):

```json
{ "tools": { "download_file": { "enabled": false } } }
```

A disabled tool is refused by `safe_execute` with `ok=False` and an Arabic
"أداة معطّلة" error. An unknown tool is refused with "أداة غير معروفة". A
present-but-malformed config raises `ToolsConfigError` rather than silently
falling back (a hidden security setting must never be ignored).

## Security model

- **SSRF (`download_file`)** — `_is_safe_url` rejects non-HTTP(S) schemes,
  `localhost`/`127.0.0.1`/`::1`/`0.0.0.0`, and any private/loopback/reserved IP
  literal. Domain names are allowed; the check is applied *before* `aria2c`
  runs. The output directory must stay inside the project workspace.
- **Path containment (`read_file`)** — every path is `Path.resolve(strict=True)`
  and must be relative to one of `allowed_roots`; `..` traversal and symlink
  escapes are neutralised, non-files and files over 256 KB are refused.
- **Sandbox (`execute_code`)** — code runs in the subprocess sandbox with a hard
  timeout; output is capped at 10 KB.
- **One gate** — `safe_execute` is the only entry point. It refuses unknown or
  disabled tools and converts every internal exception into `ok=False`, so a
  broken tool becomes an observation the model can route around, never a crash.
