"""Secure nexus-core adapter for the real ``mcp-hub`` MCP server.

The framework's own MCP protocol is intentionally different from the official
Python SDK protocol used by mcp-hub.  :mod:`src.mcp.external` handles that
transport; this module supplies the *policy* for one concrete external server:

* launch ``python -m mcp_hub.mcp_server`` with a minimal child environment;
* expose only the read-only catalog tools declared in ``MCP_HUB_READ_TOOLS``;
* publish agent-facing names as ``mcp_hub.<tool>``;
* validate the handshake and tool list before handing the client to an agent;
* plug directly into the existing :class:`~src.mcp.bridge.MCPToolExecutor`.

Nothing here mutates mcp-hub, calls a shell, or reads secrets from the parent
environment.  The optional ``pythonpath`` is an explicit administrator setting
for source checkouts; installed wheels do not need it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.mcp.bridge import MCPToolExecutor
from src.mcp.external import ExternalMCPClient, ExternalMCPError, ExternalServerConfig
from src.tools.executor import ToolCall

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.mcp.external import AuditEvent

__all__ = [
    "MCP_HUB_ARGUMENT_LIMITS",
    "MCP_HUB_MAX_CHAIN_STEPS",
    "MCP_HUB_READ_RESOURCES",
    "MCP_HUB_READ_TOOLS",
    "MCPHubConfig",
    "build_mcp_hub_client",
    "build_mcp_hub_executor",
    "mcp_hub_server_config",
    "qualified_mcp_hub_tools",
    "read_mcp_hub_resource",
    "run_mcp_hub_read_chain",
]

#: A practical agent flow should be short and auditable. The chain runner
#: rejects longer sequences before starting a subprocess.
MCP_HUB_MAX_CHAIN_STEPS = 5

#: The complete read-only tool surface of mcp-hub 1.10.0.  Adding a tool here
#: is an explicit policy decision, never an automatic consequence of discovery.
MCP_HUB_READ_TOOLS: frozenset[str] = frozenset(
    {
        "search_servers",
        "get_server",
        "list_categories",
        "servers_by_category",
        "provenance_conflicts",
        "provenance_events",
        "doctor_report",
        "suggest_category",
        "query_catalog",
    }
)

#: The read-only resource surface of mcp-hub 1.10.0.  This is adapter policy;
#: the server's own RESOURCE_SPECS are never discovered into or modified here.
MCP_HUB_READ_RESOURCES: frozenset[str] = frozenset({"mcp-hub://stats"})

#: Numeric bounds that the official SDK schema does not always advertise.
#: These mirror the mcp-hub 1.10.0 read-only tool contracts; they are policy,
#: not discovery data, and are enforced before any tools/call request.
MCP_HUB_ARGUMENT_LIMITS: Mapping[str, Mapping[str, Mapping[str, int]]] = {
    "search_servers": {"limit": {"minimum": 1, "maximum": 100}},
    "servers_by_category": {"limit": {"minimum": 1, "maximum": 100}},
    "provenance_events": {"limit": {"minimum": 1, "maximum": 50}},
    "query_catalog": {"limit": {"minimum": 1, "maximum": 200}},
}

_NAMESPACE = "mcp_hub"
_PREFIX = f"{_NAMESPACE}."


def _normalise_tool(name: str) -> str:
    """Accept qualified or bare names, returning the bare mcp-hub tool name."""
    bare = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    if bare not in MCP_HUB_READ_TOOLS:
        raise ValueError(f"unknown mcp-hub tool {name!r}")
    return bare


@dataclass(frozen=True, slots=True)
class MCPHubConfig:
    """Deployment settings for one mcp-hub subprocess."""

    db_path: str | Path = "mcp_hub.sqlite3"
    pythonpath: str | Path | None = None
    allowed_tools: frozenset[str] = field(default_factory=lambda: MCP_HUB_READ_TOOLS)
    allowed_resources: frozenset[str] = field(default_factory=lambda: MCP_HUB_READ_RESOURCES)
    timeout_s: float = 10.0
    max_output_chars: int = 12_000
    max_reconnects: int = 1
    max_call_retries: int = 1

    def __post_init__(self) -> None:
        """Reject empty paths and tools outside the known read-only surface."""
        if not str(self.db_path).strip() or "\x00" in str(self.db_path):
            raise ValueError("db_path must be a non-empty path")
        if self.pythonpath is not None and not str(self.pythonpath).strip():
            raise ValueError("pythonpath must be a non-empty path when provided")
        if self.max_call_retries < 0 or self.max_call_retries > 2:
            raise ValueError("max_call_retries must be between 0 and 2")
        normalised = frozenset(_normalise_tool(name) for name in self.allowed_tools)
        object.__setattr__(self, "allowed_tools", normalised)
        resources = frozenset(self.allowed_resources)
        if not all(isinstance(uri, str) and uri for uri in resources):
            raise ValueError("allowed_resources must contain non-empty URIs")
        if not resources <= MCP_HUB_READ_RESOURCES:
            raise ValueError("resource URIs must be within the mcp-hub read-only allowlist")
        object.__setattr__(self, "allowed_resources", resources)


def qualified_mcp_hub_tools(tools: frozenset[str]) -> frozenset[str]:
    """Render mcp-hub tool names as agent-facing, namespace-qualified names."""
    return frozenset(f"{_PREFIX}{name}" for name in tools)


def mcp_hub_server_config(config: MCPHubConfig | None = None) -> ExternalServerConfig:
    """Translate policy into the generic external-server config."""
    settings = config or MCPHubConfig()
    overrides: dict[str, str] = {"MCP_HUB_DB": str(Path(settings.db_path).expanduser())}
    if settings.pythonpath is not None:
        overrides["PYTHONPATH"] = str(Path(settings.pythonpath).expanduser())
    return ExternalServerConfig(
        name=_NAMESPACE,
        command=(sys.executable, "-m", "mcp_hub.mcp_server"),
        env=overrides,
        allowed_tools=settings.allowed_tools,
        allowed_resources=settings.allowed_resources,
        timeout_s=settings.timeout_s,
        max_output_chars=settings.max_output_chars,
        max_reconnects=settings.max_reconnects,
        max_call_retries=settings.max_call_retries,
        retry_safe_tools=settings.allowed_tools,
        argument_limits=MCP_HUB_ARGUMENT_LIMITS,
        tool_namespace=_NAMESPACE,
    )


def build_mcp_hub_client(
    config: MCPHubConfig | None = None,
    *,
    on_audit: Callable[[AuditEvent], None] | None = None,
) -> ExternalMCPClient:
    """Start, handshake and discover a real mcp-hub server, or raise cleanly."""
    client = ExternalMCPClient(mcp_hub_server_config(config), on_audit=on_audit)
    try:
        client.list_tools()
    except Exception:
        client.close()
        raise
    return client


def build_mcp_hub_executor(
    config: MCPHubConfig | None = None,
    *,
    on_audit: Callable[[AuditEvent], None] | None = None,
    max_steps: int = 5,
    max_calls_per_step: int = 5,
) -> MCPToolExecutor:
    """Build the existing agent tool bridge over a real mcp-hub subprocess."""
    settings = config or MCPHubConfig()
    client = build_mcp_hub_client(settings, on_audit=on_audit)
    return MCPToolExecutor(
        client,
        max_steps=max_steps,
        max_calls_per_step=max_calls_per_step,
        allowed_tools=qualified_mcp_hub_tools(settings.allowed_tools),
    )


def read_mcp_hub_resource(
    uri: str,
    *,
    config: MCPHubConfig | None = None,
    on_audit: Callable[[AuditEvent], None] | None = None,
) -> str:
    """Read one allowlisted mcp-hub resource through the bounded adapter.

    The URI is checked before any subprocess starts.  The generic client emits
    exactly one content-free audit event for the logical ``resources/read`` call.
    """
    settings = config or MCPHubConfig()
    if not isinstance(uri, str) or not uri or uri not in settings.allowed_resources:
        raise ExternalMCPError("resource is not allowed by mcp-hub policy", code=-32001)
    client = build_mcp_hub_client(settings, on_audit=on_audit)
    try:
        return client.read_resource(uri)
    finally:
        client.close()


def run_mcp_hub_read_chain(
    steps: Sequence[tuple[str, Mapping[str, Any] | Callable[[tuple[str, ...]], Mapping[str, Any]]]],
    *,
    config: MCPHubConfig | None = None,
    allowed_tools: frozenset[str] | None = None,
    on_audit: Callable[[AuditEvent], None] | None = None,
) -> tuple[str, ...]:
    """Run a short, fail-fast read chain through a real ``MCPToolExecutor``.

    Each step may either carry a static argument mapping or a callable that
    receives the previous step outputs.  Tools are checked against the
    configured read-only allowlist before the child process starts, so a chain
    that tries to widen its own permissions emits no tool call and no audit
    event.  Outputs are returned to the caller; audit events stay content-free.
    """
    if not steps or len(steps) > MCP_HUB_MAX_CHAIN_STEPS:
        raise ValueError(f"read chain must have 1..{MCP_HUB_MAX_CHAIN_STEPS} steps")

    settings = config or MCPHubConfig()
    permitted = (
        settings.allowed_tools
        if allowed_tools is None
        else frozenset(_normalise_tool(name) for name in allowed_tools)
    )
    if not permitted:
        raise ValueError("allowed_tools must not be empty")
    if not permitted <= settings.allowed_tools:
        raise ValueError("read chain tools must be within the mcp-hub read-only allowlist")

    prepared: list[
        tuple[str, Mapping[str, Any] | Callable[[tuple[str, ...]], Mapping[str, Any]]]
    ] = []
    for name, arguments in steps:
        bare = _normalise_tool(name)
        if bare not in permitted:
            raise ValueError(f"read chain tool {name!r} is not permitted")
        if not isinstance(arguments, Mapping) and not callable(arguments):
            raise ValueError("read chain arguments must be a mapping or a callable")
        prepared.append((bare, arguments))

    executor = build_mcp_hub_executor(
        settings, on_audit=on_audit, max_steps=1, max_calls_per_step=1
    )
    outputs: list[str] = []
    try:
        for index, (bare, arguments) in enumerate(prepared, start=1):
            resolved: Mapping[str, Any]
            if isinstance(arguments, Mapping):
                resolved = arguments
            else:
                candidate = arguments(tuple(outputs))
                if not isinstance(candidate, Mapping):
                    raise ValueError(f"read chain step {index} must return an argument mapping")
                resolved = candidate
            outcome = executor.execute(
                ToolCall(f"{_PREFIX}{bare}", dict(resolved)),
                allowed_tools=qualified_mcp_hub_tools(permitted),
            )
            if not outcome.ok:
                raise ExternalMCPError(
                    f"mcp-hub read chain stopped at step {index} ({bare})",
                    code=-32021,
                    data={"step": index, "tool": bare},
                )
            outputs.append(str(outcome.output or ""))
        return tuple(outputs)
    finally:
        executor.client.close()


def audit_dict(event: AuditEvent) -> dict[str, Any]:
    """JSON-safe view for callers that persist audit events."""
    return event.to_dict()
