"""Model Context Protocol (MCP) primitives — standard library only.

Targets the stateless **2026-07-28** revision: every request carries its
protocol version and client capabilities in ``_meta`` and the
``initialize``/``initialized`` handshake is gone. Servers advertise themselves
with ``server/discover`` and identify themselves in every result's ``_meta``.

The module holds the wire-level pieces only (constants, the error model, JSON-RPC
message builders, content blocks and the tool contract) — nothing here imports a
transport, an agent or a third-party package, so it is safe on the phone.

Protocol: JSON-RPC 2.0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "JSONRPC_VERSION",
    "MCP_PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "META_PROTOCOL_VERSION",
    "META_CLIENT_INFO",
    "META_CLIENT_CAPABILITIES",
    "META_SERVER_INFO",
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "MISSING_REQUIRED_CLIENT_CAPABILITY",
    "UNSUPPORTED_PROTOCOL_VERSION",
    "MCPError",
    "TextContent",
    "ToolSpec",
    "text_content",
    "error_content",
    "jsonrpc_result",
    "jsonrpc_error",
    "server_meta",
    "request_protocol_version",
    "request_client_info",
]

#: The JSON-RPC envelope version every message must carry.
JSONRPC_VERSION = "2.0"

#: The MCP revision this implementation speaks.
MCP_PROTOCOL_VERSION = "2026-07-28"

#: Revisions we can serve, newest first. Used for version negotiation and the
#: ``server/discover`` advert. ``2026-07-28`` is the current protocol version.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2026-07-28",
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

#: Per-request ``_meta`` keys defined by the specification (2026-07-28).
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

#: JSON-RPC 2.0 reserved error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: MCP-specific error codes (2026-07-28).
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022


class MCPError(Exception):
    """An error that maps onto a JSON-RPC error object.

    Raise it (or a subclass) inside a tool handler or the request dispatcher to
    return a specific JSON-RPC ``code`` to the caller instead of a generic
    ``-32603`` internal error.
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self) -> dict[str, Any]:
        """The ``error`` object for a JSON-RPC response."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


@dataclass(frozen=True, slots=True)
class TextContent:
    """A ``text`` content block returned from ``tools/call``."""

    text: str
    type: str = "text"

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serialisable block."""
        return {"type": self.type, "text": self.text}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool's public contract — name, description and JSON input schema.

    Carries no handler, so it is trivially serialisable for ``tools/list``.
    """

    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    title: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Render as the object ``tools/list`` expects."""
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": dict(self.input_schema),
        }
        if self.title:
            payload["title"] = self.title
        return payload


def text_content(text: str) -> dict[str, Any]:
    """A successful ``tools/call`` result wrapping one text block."""
    return {"content": [TextContent(text).to_dict()], "isError": False}


def error_content(message: str) -> dict[str, Any]:
    """A ``tools/call`` result that reports a tool-level failure.

    Tool failures travel as ``isError: true`` content (not JSON-RPC errors) so
    the model can read and react to them, exactly as the spec intends.
    """
    return {"content": [TextContent(message).to_dict()], "isError": True}


def jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC success response."""
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    """Build a JSON-RPC error response."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": error}


def server_meta(name: str, version: str) -> dict[str, Any]:
    """The ``_meta`` block a server SHOULD attach to every result."""
    return {META_SERVER_INFO: {"name": name, "version": version}}


def request_protocol_version(params: Mapping[str, Any]) -> str | None:
    """Extract a request's declared protocol version (2026 ``_meta`` or legacy).

    The stateless 2026 revision puts it under ``params._meta``; a legacy
    ``initialize`` carried a top-level ``protocolVersion``. Returns ``None``
    when the caller declared neither (allowed for ``server/discover``).
    """
    meta = params.get("_meta")
    if isinstance(meta, Mapping):
        value = meta.get(META_PROTOCOL_VERSION)
        if isinstance(value, str):
            return value
    legacy = params.get("protocolVersion")
    return legacy if isinstance(legacy, str) else None


def request_client_info(params: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Extract the optional client identity (``_meta[...clientInfo]``)."""
    meta = params.get("_meta")
    if isinstance(meta, Mapping):
        info = meta.get(META_CLIENT_INFO)
        if isinstance(info, Mapping):
            return info
    return None
