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

## Failure behaviour

- Handshake or discovery failure closes the child and raises `ExternalMCPError`.
- Permission denial uses code `-32001`; unadvertised tool `-32601`; invalid arguments `-32602`; server/tool errors preserve the server code when numeric.
- A dead child is detected at readiness time, so reconnect budget accounting is deterministic rather than dependent on reader-thread timing.
- Transport failures (`ExternalMCPTransportError`) are distinct from tool/policy errors. Only an explicitly safe, read-only tool is replayed after one bounded restart; the caller still sees a single audit event.
- `MCPToolExecutor.execute()` converts all errors into `ToolOutcome` instead of crashing the agent loop.

## Tests

- Unit: `tests/test_external_mcp.py` uses deterministic fake SDK servers for handshake, `notifications/initialized`, discovery, schema and numeric-limit validation, output sanitisation, size limits, audit shape, bounded read-only transport retry, reconnect and spawn errors.
- Real process: the same file's `integration`-marked tests start an actual `mcp-hub` subprocess against a temporary SQLite database, seed servers, and drive a real `MCPToolExecutor` agent loop through `mcp_hub.search_servers` and `mcp_hub.query_catalog`. They also assert permission denial, a structured `-32602` for `limit: 201`, content-free audit events, reconnect success and reconnect-budget exhaustion.
- The dedicated `.github/workflows/mcp-hub-integration.yml` installs `mcp>=1.27,<3` and the pinned `mcp-hub==1.10.0` wheel so the real-process tests are not skipped. It is a separate workflow to avoid overlap with open PRs that already modify `test.yml`.
- Locally, set `MCP_HUB_ROOT=/path/to/mcp-hub-checkout` to run those tests against a source tree; the fixture adds `<root>/src` to the child `PYTHONPATH`.

## General MCP server management layer (assessment only)

The adapter is deliberately one server, one process, one policy. A future multi-server layer would need, in this order:

1. A registry of named server configs (command, cwd, env allowlist, transport, protocol family, tool namespace).
2. Lifecycle management (start, health, restart budget, clean shutdown) owned per server, not per call.
3. Discovery caching with explicit fingerprinting, so tool drift is visible before an agent sees new capabilities.
4. Per-agent policy resolution (allow/deny, argument limits, output limits) applied before transport dispatch.
5. Health/recovery telemetry using the same content-free audit event shape.
6. A routing table that maps agent-facing names to server namespaces without trusting discovery.

That layer is **not implemented here**. Only the mcp-hub slice and its reusable stdio transport are shipped.
