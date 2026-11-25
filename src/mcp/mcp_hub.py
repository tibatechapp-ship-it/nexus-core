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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.mcp.bridge import MCPToolExecutor
from src.mcp.external import ExternalMCPClient, ExternalServerConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.mcp.external import AuditEvent

__all__ = [
    "MCP_HUB_READ_TOOLS",
    "MCPHubConfig",
    "build_mcp_hub_client",
    "build_mcp_hub_executor",
    "mcp_hub_server_config",
    "qualified_mcp_hub_tools",
]

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
    timeout_s: float = 10.0
    max_output_chars: int = 12_000
    max_reconnects: int = 1

    def __post_init__(self) -> None:
        """Reject empty paths and tools outside the known read-only surface."""
        if not str(self.db_path).strip() or "\x00" in str(self.db_path):
            raise ValueError("db_path must be a non-empty path")
        if self.pythonpath is not None and not str(self.pythonpath).strip():
            raise ValueError("pythonpath must be a non-empty path when provided")
        normalised = frozenset(_normalise_tool(name) for name in self.allowed_tools)
        object.__setattr__(self, "allowed_tools", normalised)


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
        timeout_s=settings.timeout_s,
        max_output_chars=settings.max_output_chars,
        max_reconnects=settings.max_reconnects,
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


def audit_dict(event: AuditEvent) -> dict[str, Any]:
    """JSON-safe view for callers that persist audit events."""
    return event.to_dict()
