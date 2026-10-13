"""MCP clients — drive an MCP server in-process or as a stdio subprocess.

Two transports, one shape:

* :class:`InProcessClient` talks straight to an :class:`~src.mcp.server.MCPServer`
  object (no process, no I/O) — handy for tests and for agents that host a server.
* :class:`StdioClient` spawns ``command`` and speaks newline-delimited JSON-RPC
  over its stdin/stdout, the standard way an MCP host launches a server.

:func:`to_tool_schemas` bridges a server's ``tools/list`` output into the
framework's own :class:`~src.tools.schemas.ToolSchema`, so framework agents can
consume remote MCP tools through the existing tool machinery.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.mcp.protocol import JSONRPC_VERSION
from src.mcp.server import MCPServer
from src.tools.schemas import ToolParameter, ToolSchema

__all__ = [
    "MCPClientError",
    "InProcessClient",
    "StdioClient",
    "content_text",
    "default_server_command",
    "to_tool_schemas",
]

_VALID_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})


class MCPClientError(RuntimeError):
    """Raised when a server returns a JSON-RPC error or drops the connection."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


def content_text(result: Mapping[str, Any]) -> str:
    """Join every ``text`` block of a ``tools/call`` result into one string."""
    blocks = result.get("content")
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, Mapping) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _raise_for_error(response: Mapping[str, Any]) -> None:
    """Turn a JSON-RPC ``error`` object into an :class:`MCPClientError`."""
    error = response.get("error")
    if isinstance(error, Mapping):
        raise MCPClientError(
            str(error.get("message", "unknown error")),
            code=error.get("code") if isinstance(error.get("code"), int) else None,
            data=error.get("data"),
        )


class InProcessClient:
    """Call a live :class:`MCPServer` object directly, with no subprocess."""

    def __init__(self, server: MCPServer) -> None:
        self._server = server
        self._next_id = 0

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Send ``method`` and return its ``result`` (raising on an error object)."""
        self._next_id += 1
        message = {
            "jsonrpc": JSONRPC_VERSION,
            "id": self._next_id,
            "method": method,
            "params": dict(params or {}),
        }
        response = self._server.handle_request(message)
        if response is None:
            raise MCPClientError(f"server returned no response for {method!r}")
        _raise_for_error(response)
        return response.get("result")

    def discover(self) -> Mapping[str, Any]:
        """``server/discover`` — the server's versions, capabilities and identity."""
        result = self.request("server/discover")
        return result if isinstance(result, Mapping) else {}

    def list_tools(self) -> list[dict[str, Any]]:
        """``tools/list`` — the server's tool contracts."""
        result = self.request("tools/list")
        if isinstance(result, Mapping):
            tools = result.get("tools")
            if isinstance(tools, list):
                return [dict(tool) for tool in tools if isinstance(tool, Mapping)]
        return []

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> str:
        """``tools/call`` — run a tool and return its text content."""
        result = self.request("tools/call", {"name": name, "arguments": dict(arguments or {})})
        return content_text(result) if isinstance(result, Mapping) else ""


class StdioClient:
    """Drive an MCP server subprocess over its stdio (JSON-RPC, line-delimited).

    Usable as a context manager::

        with StdioClient(["python", "-m", "src.mcp"]) as client:
            print(client.list_tools())

    The child is launched lazily on the first request and respawned if it exits.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self.command: list[str] = list(command)
        self.env: dict[str, str] | None = dict(env) if env is not None else None
        self.cwd = cwd
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Spawn the server subprocess (idempotent)."""
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(  # noqa: S603 - command is caller-supplied
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self.env,
            cwd=self.cwd,
        )

    def close(self) -> None:
        """Terminate the subprocess if it is running."""
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
                proc.kill()

    def __enter__(self) -> "StdioClient":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def running(self) -> bool:
        """Whether the subprocess is currently alive."""
        return self._proc is not None and self._proc.poll() is None

    # -- protocol ----------------------------------------------------------
    def request(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Send one request and block for its response."""
        self.start()
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:  # pragma: no cover
            raise MCPClientError("server process is not available")
        self._next_id += 1
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": self._next_id,
            "method": method,
            "params": dict(params or {}),
        }
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise MCPClientError("server closed the connection")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"invalid JSON from server: {exc}") from exc
        if not isinstance(response, Mapping):
            raise MCPClientError("server response is not a JSON object")
        _raise_for_error(response)
        return response.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        """``tools/list`` over stdio."""
        result = self.request("tools/list")
        if isinstance(result, Mapping):
            tools = result.get("tools")
            if isinstance(tools, list):
                return [dict(tool) for tool in tools if isinstance(tool, Mapping)]
        return []

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> str:
        """``tools/call`` over stdio."""
        result = self.request("tools/call", {"name": name, "arguments": dict(arguments or {})})
        return content_text(result) if isinstance(result, Mapping) else ""


def to_tool_schemas(
    tools: Iterable[Mapping[str, Any]],
    *,
    prefix: str = "",
) -> list[ToolSchema]:
    """Convert MCP ``tools/list`` entries into framework :class:`ToolSchema` objects.

    ``prefix`` is prepended to each name (e.g. ``"mcp_"``) so remote tools never
    collide with local ones. Parameter types outside the JSON-schema primitives
    fall back to ``"string"``.
    """
    schemas: list[ToolSchema] = []
    for spec in tools:
        raw_name = spec.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        schema = spec.get("inputSchema")
        schema = schema if isinstance(schema, Mapping) else {}
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        required = schema.get("required")
        required_names = {name for name in required} if isinstance(required, list) else set()
        parameters: list[ToolParameter] = []
        for param_name, prop in properties.items():
            prop = prop if isinstance(prop, Mapping) else {}
            param_type = prop.get("type")
            if not isinstance(param_type, str) or param_type not in _VALID_JSON_TYPES:
                param_type = "string"
            description = prop.get("description")
            parameters.append(
                ToolParameter(
                    name=str(param_name),
                    type=param_type,
                    description=description if isinstance(description, str) else "",
                    required=param_name in required_names,
                )
            )
        description = spec.get("description")
        schemas.append(
            ToolSchema(
                name=f"{prefix}{raw_name}",
                description=description if isinstance(description, str) else "",
                parameters=tuple(parameters),
            )
        )
    return schemas


def default_server_command() -> list[str]:
    """The command to launch this repository's framework MCP server over stdio."""
    return [sys.executable, "-m", "src.mcp"]
