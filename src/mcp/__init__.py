"""MCP layer — a standard-library Model Context Protocol server and client.

nexus-core speaks MCP ``2026-07-28`` (the stateless revision): a server
advertises itself with ``server/discover`` and carries ``serverInfo`` in every
result's ``_meta``; the legacy ``initialize`` handshake is still answered for
older clients.

Quick start::

    from src.mcp import build_framework_server, InProcessClient

    client = InProcessClient(build_framework_server(root="."))
    print(client.list_tools())
    print(client.call_tool("list_dir", {"path": "."}))

Run the framework server over stdio (for Claude Desktop, Cursor, …)::

    python -m src.mcp
"""

from __future__ import annotations

from src.mcp.bridge import MCPToolExecutor
from src.mcp.client import (
    InProcessClient,
    MCPClientError,
    StdioClient,
    content_text,
    default_server_command,
    to_tool_schemas,
)
from src.mcp.framework import build_framework_server, serve_framework
from src.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
    MCPError,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    UNSUPPORTED_PROTOCOL_VERSION,
    TextContent,
    ToolSpec,
    error_content,
    jsonrpc_error,
    jsonrpc_result,
    request_client_info,
    request_protocol_version,
    server_meta,
    text_content,
)
from src.mcp.server import MCPServer, Tool, schema_from_signature, tool_from_callable

__all__ = [
    # protocol
    "JSONRPC_VERSION",
    "MCP_PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
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
    # server
    "MCPServer",
    "Tool",
    "schema_from_signature",
    "tool_from_callable",
    # client
    "MCPClientError",
    "InProcessClient",
    "StdioClient",
    "content_text",
    "default_server_command",
    "to_tool_schemas",
    # agent bridge
    "MCPToolExecutor",
    # framework surface
    "build_framework_server",
    "serve_framework",
]
