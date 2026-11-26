# MCP Hub integration

`nexus-core` now has two distinct MCP client paths:

| Path | Protocol | Use |
| --- | --- | --- |
| `StdioClient` / `InProcessClient` | NEXUS stateless `2026-07-28` (`server/discover`) | The framework's own `python -m src.mcp` server |
| `ExternalMCPClient` | Official MCP SDK (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`) over newline JSON-RPC | External servers such as `mcp-hub` |

The second path is additive. Nothing about the legacy client, server, tool contracts or default policies changed.

## Why an adapter was needed

A direct probe against `python -m mcp_hub.mcp_server` with MCP SDK 1.30 showed that a bare `tools/list` is rejected with `-32602`; the SDK requires a handshake first. The same probe confirmed newline-delimited JSON-RPC, negotiated protocol `2025-11-25`, and 9 read-only tools. The old `StdioClient` sends `tools/list` immediately, so it cannot talk to official-SDK servers without breaking its own protocol semantics.

## Quick start

```python
from src.mcp import MCPHubConfig, build_mcp_hub_executor

executor = build_mcp_hub_executor(MCPHubConfig(db_path="mcp_hub.sqlite3"))
schemas = executor.tool_schemas(prefix="")  # mcp_hub.search_servers, ...
```

A tool call from an agent uses the existing `<tool-call>` protocol:

```text
<tool-call name="mcp_hub.search_servers" args='{"query":"database"}'/>
```

Agent-facing names are namespace-qualified (`mcp_hub.<tool>`). The adapter strips **only** its configured `mcp_hub.` namespace after policy checks; a bare name still works but an unrelated prefix is never accepted.

A second real flow reads the catalog with another allowed tool while keeping the same policy path:

```text
<tool-call name="mcp_hub.query_catalog" args='{"kind":"server","limit":5}'/>
```

`limit` is checked against the advertised schema (`1..200`) before any subprocess call. `mcp_hub.query_catalog` with `limit: 201` returns a structured `-32602` outcome through `MCPToolExecutor.execute()`.

## Bounded read chains

For practical work that needs more than one catalog lookup, use `run_mcp_hub_read_chain` from `src.mcp.mcp_hub`. It runs through the same `MCPToolExecutor`, keeps one child process for the whole chain, and stops at the first failed step:

```python
from src.mcp.mcp_hub import MCPHubConfig, run_mcp_hub_read_chain

config = MCPHubConfig(
    db_path="mcp_hub.sqlite3",
    allowed_tools=frozenset({"list_categories", "servers_by_category", "get_server")),
)

def category_args(previous):
    rows = json.loads(previous[-1])
    row = next(item for item in rows if item["category"] == "search")
    return {"category": row["category"], "limit": 1}

def server_args(previous):
    rows = json.loads(previous[-1])
    return {"server_id": int(rows[0]["id"])}

outputs = run_mcp_hub_read_chain(
    [
        ("mcp_hub.list_categories", {}),
        ("mcp_hub.servers_by_category", category_args),
        ("mcp_hub.get_server", server_args),
    ],
    config=config,
)
```

Each step may carry a static argument mapping or a callable that receives earlier outputs. Chains are limited to `MCP_HUB_MAX_CHAIN_STEPS` (5) steps. The optional `allowed_tools` argument can narrow the chain below the config allowlist; both are checked before the subprocess starts, so an attempt to widen permission emits no tool call and no audit event. A failed step raises `ExternalMCPError` with code `-32021` and content-free `data` (`step`, `tool`).

## Policy and safety

- `MCP_HUB_READ_TOOLS` is an explicit read-only allowlist of the 9 current tools. Discovery cannot add tools outside it.
- `MCPHubConfig.allowed_tools` can narrow the list further per agent. Unknown tool names are rejected at configuration time.
- The child environment contains only fixed passthrough variables plus `MCP_HUB_DB` (and an explicit trusted `pythonpath`). Parent API keys and tokens are not inherited.
- The command is a tuple passed without `shell=True`.
- Inputs are validated against the server's advertised JSON schema before a call is sent. Because the official SDK schema can drop JSON-Schema `minimum` / `maximum` keywords, `MCP_HUB_ARGUMENT_LIMITS` re-applies the known read-only tool bounds as adapter policy (for example `query_catalog.limit <= 200`).
- Tool output is bounded, neutralised for `<tool-call>` / `<system>` / `<|...|>` marker injection, and treated as data.
- Audit events record server, tool, success, duration, output length and error code — never arguments or output content.
- Reconnection is bounded (default: one restart per 60 seconds). A transport failure may be replayed **once** only for tools in the explicit `retry_safe_tools` set — for mcp-hub that is the same read-only allowlist. Policy, schema and tool errors are never replayed. One audit event is emitted per logical call.

`pythonpath` is an administrator setting for source checkouts. With the published wheel it should be left unset.

## Bounded resource reads

`resources/read` is exposed as a separate read-only path. The URI is checked
against `MCP_HUB_READ_RESOURCES` (`mcp-hub://stats` in 1.10.0) before any
subprocess starts; discovery cannot widen that allowlist.

```python
from src.mcp.mcp_hub import MCPHubConfig, read_mcp_hub_resource

text = read_mcp_hub_resource("mcp-hub://stats", config=MCPHubConfig(db_path="mcp_hub.sqlite3"))
```

Resource text is bounded, neutralised for marker injection and treated as data.
One content-free audit event is emitted for the logical call (`server`,
`tool=resources/read`, `ok`, `duration_ms`, `chars`, `error_code`); the URI and
body are never logged. There is no tool replay for resource reads.

## Read-only policy preflight

The framework server registers `dry_run_policy` by default.  It answers a
structural question before real work: would the current policy accept this
step?  It never starts a subprocess, writes a file, runs a command or reads a
secret.  Callers can disable it with `build_framework_server(include_preflight=False)`.

```python
from src.mcp import build_framework_server

server = build_framework_server(root=".")
decision = server.call_tool("dry_run_policy", {"kind": "resource_read", "uri": "mcp-hub://stats"})
```

Supported `kind` values are `tool_call`, `resource_read`, `path` and `plan`.
The result contains only `ok`, a stable `reason` (for example `allowed`,
`tool_not_allowed`, `path_outside_workspace`, `parameter_above_maximum`),
`code` and `kind`.  No checked value is echoed back. Path checks are confined
to the server root, refuse symlinks and sensitive names, and plan checks are
structural only — no file is read or changed. Preflight uses the same
default-deny allowlists and numeric limits as the real adapter and emits one
content-free audit event per call.

## Failure behaviour

- Handshake or discovery failure closes the child and raises `ExternalMCPError`.
- Permission denial uses code `-32001`; unadvertised tool `-32601`; invalid arguments `-32602`; server/tool errors preserve the server code when numeric.
- A dead child is detected at readiness time, so reconnect budget accounting is deterministic rather than dependent on reader-thread timing.
- Transport failures (`ExternalMCPTransportError`) are distinct from tool/policy errors. Only an explicitly safe, read-only tool is replayed after one bounded restart; the caller still sees a single audit event.
- `MCPToolExecutor.execute()` converts all errors into `ToolOutcome` instead of crashing the agent loop.

## Tests

- Unit: `tests/test_external_mcp.py` uses deterministic fake SDK servers for handshake, `notifications/initialized`, discovery, schema and numeric-limit validation, output sanitisation, size limits, audit shape, bounded read-only transport retry, reconnect and spawn errors.
- Real process: the same file's `integration`-marked tests start an actual `mcp-hub` subprocess against a temporary SQLite database, seed servers, and drive a real `MCPToolExecutor` agent loop through `mcp_hub.search_servers` and `mcp_hub.query_catalog`. They also assert a three-step `run_mcp_hub_read_chain` that passes discovered categories and server IDs between steps, fail-fast `-32021` on a missing server, permission denial, a structured `-32602` for `limit: 201`, content-free audit events, reconnect success and reconnect-budget exhaustion.
- The dedicated `.github/workflows/mcp-hub-integration.yml` installs `mcp>=1.27,<3` and the pinned `mcp-hub==1.10.0` wheel so the real-process tests are not skipped. It is a separate workflow to avoid overlap with open PRs that already modify `test.yml`.
- Locally, set `MCP_HUB_ROOT=/path/to/mcp-hub-checkout` to run those tests against a source tree; the fixture adds `<root>/src` to the child `PYTHONPATH`.

## Opt-in dev-bounded coder tools

The framework server stays read-only by default. Dev-bounded coder tools are
**not registered** unless the server is built with `include_dev_tools=True`:

```python
from src.mcp import build_framework_server

server = build_framework_server(root=".", include_dev_tools=True)
```

Even when registered, mutating calls require both `NEXUS_ENABLE_DEV_TOOLS=1`
and an explicit per-call `approval` decision. `NEXUS_ENABLE_DEV_TOOLS` is not
set in `.env.example` because it is an opt-in capability gate, not routine
configuration.

| Tool | Mode | Contract |
| --- | --- | --- |
| `coder_plan_preview` | read-only | Returns a unified diff for a validated plan; never writes files and needs no approval. |
| `coder_apply_plan` | dev-bounded | Applies a pre-validated `RepairPlan` inside the exact server `workspace_root`; refuses traversal, symlinks, sensitive dirs/files, oversized content and invalid Python syntax. |
| `coder_run_tests` | dev-bounded | Runs only `pytest`, `ruff` or `mypy` on explicit workspace-confined targets; argv list, no shell, no network, timeout capped at `120s` and output at `64 KiB`. |
| `coder_container_run` | container-sandbox | Blocked unless `NEXUS_ENABLE_CONTAINER_SANDBOX=1`, the image is pinned with `@sha256:<64 hex>` and an explicit human approval is supplied. |

Every call emits exactly one audit event with `tool`, `permission_mode`, `ok`,
`duration_ms`, `chars` and `error_code` only. Arguments, outputs, paths,
approval tokens and secrets are never recorded. The default registry used by
`AgentLoop` and `HybridRouter._run_loop()` contains no `write_file` or
`run_agent`; nested-agent dispatch and direct writes must be requested through
the explicit dev registry.

## Opt-in bounded project memory and task plans

A second opt-in group gives Zyko project-scoped memory and a bounded work plan.
It is **not registered** unless the framework server is built with
`include_memory_tools=True`:

```python
from src.mcp import build_framework_server

server = build_framework_server(root=".", include_memory_tools=True)
```

The default database is `.zyko/memory.db` inside the server `workspace`. A
custom `memory_db_path=` is accepted only when it stays inside that workspace,
contains no `..` segments, no symlink components and no sensitive directory or
secret-like filename.

| Tool | Mode | Contract |
| --- | --- | --- |
| `memory_recall` | read-only | Searches only the exact `project`/`session` scope, scores up to 64 recent facts, redacts secret-shaped values and returns at most 8 bounded results. |
| `memory_record` | bounded write | Stores one fact (max 4096 chars) under the exact scope. Requires `NEXUS_ENABLE_MEMORY_WRITES=1` and an explicit per-call `approval`. Secret-shaped content is refused. |
| `task_plan_get` | read-only | Returns the scoped plan with a `done`/`doing`/`todo` summary and redacted step text. |
| `task_plan_update` | bounded write | Replaces the scoped plan atomically (1..32 steps, 64-char ids, 256-char text, 8 KiB serialized cap) with an optional `expected_version` conflict guard. Requires the same env gate and approval. |

Scope ids match `[A-Za-z0-9._:@-]{1,128}`; Arabic-Indic digits and other
characters are rejected before any database access. There is no cross-scope
read path: `project` and `session` are always required. Memory facts are stored
through `MemoryManager.semantic` with subject `project/session`, while plans are
keyed by `(project, session)` in a small `task_plans` table.

Every call emits exactly one content-free audit event with `tool`,
`permission_mode`, `ok`, `duration_ms`, `chars` and `error_code` only. Scope
ids, arguments, memory text, plan text and approval tokens are never recorded.

## General MCP server management layer (assessment only)

The adapter is deliberately one server, one process, one policy. A future multi-server layer would need, in this order:

1. A registry of named server configs (command, cwd, env allowlist, transport, protocol family, tool namespace).
2. Lifecycle management (start, health, restart budget, clean shutdown) owned per server, not per call.
3. Discovery caching with explicit fingerprinting, so tool drift is visible before an agent sees new capabilities.
4. Per-agent policy resolution (allow/deny, argument limits, output limits) applied before transport dispatch.
5. Health/recovery telemetry using the same content-free audit event shape.
6. A routing table that maps agent-facing names to server namespaces without trusting discovery.

That layer is **not implemented here**. Only the mcp-hub slice and its reusable stdio transport are shipped.
