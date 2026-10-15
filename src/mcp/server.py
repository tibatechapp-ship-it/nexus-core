"""MCPServer — a standard-library Model Context Protocol server.

Register tools (a name, a JSON schema and a handler) and drive them either
in-process or from a parent process over stdio (newline-delimited JSON-RPC).

Targets protocol **2026-07-28**: the server advertises itself with
``server/discover``, attaches ``serverInfo`` to every result's ``_meta``, and
does not require the ``initialize`` handshake. A legacy ``initialize`` request
is still answered so older clients (2025-xx era) keep working unchanged.

Nothing here needs a third-party package.
"""

from __future__ import annotations

import inspect
import json
import logging
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import IO, Any

from src.mcp.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    UNSUPPORTED_PROTOCOL_VERSION,
    INTERNAL_ERROR,
    MCPError,
    ToolSpec,
    error_content,
    jsonrpc_error,
    jsonrpc_result,
    request_protocol_version,
    server_meta,
    text_content,
)

__all__ = [
    "Tool",
    "MCPHandler",
    "MCPServer",
    "schema_from_signature",
    "tool_from_callable",
]

logger = logging.getLogger("src.mcp.server")

#: A tool handler receives the call's ``arguments`` mapping and returns either a
#: string (wrapped as text) or a full ``{content, isError}`` tool result.
MCPHandler = Callable[[Mapping[str, Any]], Any]

_JSON_TYPE_NAMES: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "tuple": "array",
    "dict": "object",
    "Mapping": "object",
    "Sequence": "array",
}


@dataclass(frozen=True, slots=True)
class Tool:
    """A registered tool: its public :class:`ToolSpec` plus the handler to run."""

    name: str
    handler: MCPHandler
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    title: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name must be non-empty")

    def spec(self) -> ToolSpec:
        """The handler-free contract sent over the wire."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema or {}),
            title=self.title,
        )


class MCPServer:
    """A registry of tools plus the JSON-RPC dispatch over them."""

    def __init__(
        self,
        name: str = "nexus-core",
        version: str = "0.0.0",
        *,
        instructions: str | None = None,
        protocol_version: str = MCP_PROTOCOL_VERSION,
        supported_versions: Iterable[str] = SUPPORTED_PROTOCOL_VERSIONS,
    ) -> None:
        self.name = name
        self.version = version
        self.instructions = instructions
        self.protocol_version = protocol_version
        self.supported_versions: tuple[str, ...] = tuple(supported_versions)
        self._tools: dict[str, Tool] = {}

    # -- registration ------------------------------------------------------
    def add_tool(self, tool: Tool) -> Tool:
        """Register ``tool`` (raises on a duplicate name)."""
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def register(
        self,
        name: str,
        handler: MCPHandler,
        *,
        description: str = "",
        input_schema: Mapping[str, Any] | None = None,
        title: str | None = None,
    ) -> Tool:
        """Register a handler under ``name`` (fluent convenience)."""
        return self.add_tool(
            Tool(
                name=name,
                handler=handler,
                description=description,
                input_schema=dict(input_schema or {}),
                title=title,
            )
        )

    def tool(
        self,
        name: str,
        *,
        description: str = "",
        input_schema: Mapping[str, Any] | None = None,
    ) -> Callable[[MCPHandler], MCPHandler]:
        """Decorator form of :meth:`register` — returns the handler unchanged."""

        def decorate(handler: MCPHandler) -> MCPHandler:
            self.register(name, handler, description=description, input_schema=input_schema)
            return handler

        return decorate

    def remove_tool(self, name: str) -> None:
        """Unregister ``name`` (no error if absent)."""
        self._tools.pop(name, None)

    @property
    def tools(self) -> tuple[Tool, ...]:
        """Every registered tool, in registration order."""
        return tuple(self._tools.values())

    def tool_names(self) -> list[str]:
        """Registered tool names, sorted."""
        return sorted(self._tools)

    # -- MCP surface -------------------------------------------------------
    def server_info(self) -> dict[str, Any]:
        """This server's identity."""
        return {"name": self.name, "version": self.version}

    def capabilities(self) -> dict[str, Any]:
        """Advertised capabilities (tools only; list is static)."""
        return {"tools": {"listChanged": False}}

    def discover(self) -> dict[str, Any]:
        """``server/discover`` — versions, capabilities and identity."""
        payload: dict[str, Any] = {
            "protocolVersions": list(self.supported_versions),
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities(),
            "serverInfo": self.server_info(),
        }
        if self.instructions:
            payload["instructions"] = self.instructions
        payload["_meta"] = server_meta(self.name, self.version)
        return payload

    def list_tools(self, cursor: str | None = None) -> dict[str, Any]:
        """``tools/list`` — every tool's contract (no pagination; cursor ignored)."""
        _ = cursor  # the full list fits in one page; advertised as such
        specs = [self._tools[name].spec().to_dict() for name in self.tool_names()]
        return {
            "tools": specs,
            "ttlMs": 0,
            "cacheScope": "public",
            "_meta": server_meta(self.name, self.version),
        }

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """``tools/call`` — run ``name`` and return a tool result.

        A handler exception becomes ``isError`` content (a tool failure the model
        can read), never a crash. An unknown tool raises ``-32601``.
        """
        tool_obj = self._tools.get(name)
        if tool_obj is None:
            raise MCPError(METHOD_NOT_FOUND, f"Unknown tool: {name}")
        try:
            raw = tool_obj.handler(dict(arguments or {}))
        except MCPError:
            raise
        except Exception as exc:  # noqa: BLE001 - a tool must never crash the server
            logger.exception("tool %s failed", name)
            result = error_content(f"{type(exc).__name__}: {exc}")
        else:
            result = self._normalize_result(raw)
        result["_meta"] = server_meta(self.name, self.version)
        return result

    def ping(self) -> dict[str, Any]:
        """``ping`` — liveness probe."""
        return {"_meta": server_meta(self.name, self.version)}

    # -- dispatch ----------------------------------------------------------
    def handle_request(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC request; ``None`` means "notification, no reply"."""
        if not isinstance(request, Mapping):
            return jsonrpc_error(None, INVALID_REQUEST, "request must be a JSON object")

        req_id = request.get("id")
        is_notification = req_id is None

        def reply_error(code: int, message: str, data: Any = None) -> dict[str, Any] | None:
            if is_notification:
                return None
            return jsonrpc_error(req_id, code, message, data)

        if request.get("jsonrpc") != JSONRPC_VERSION:
            return reply_error(INVALID_REQUEST, "expected jsonrpc 2.0")

        method = request.get("method")
        if not isinstance(method, str) or not method:
            return reply_error(INVALID_REQUEST, "missing method")

        params = request.get("params")
        if not isinstance(params, Mapping):
            params = {}

        try:
            result = self._dispatch(method, params)
        except MCPError as exc:
            return reply_error(exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 - the loop must survive any bug
            logger.exception("MCP dispatch failed for %s", method)
            return reply_error(INTERNAL_ERROR, str(exc))

        if result is _NO_REPLY:
            return None
        if is_notification:
            return None
        return jsonrpc_result(req_id, result)

    def _dispatch(self, method: str, params: Mapping[str, Any]) -> Any:
        """Route a non-notification method to its handler."""
        if method == "server/discover":
            return self.discover()
        if method == "tools/list":
            self._check_version(params)
            return self.list_tools()
        if method == "tools/call":
            self._check_version(params)
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, Mapping):
                raise MCPError(INVALID_PARAMS, "arguments must be an object")
            name = params.get("name")
            if not isinstance(name, str) or not name:
                raise MCPError(INVALID_PARAMS, "tool name is required")
            return self.call_tool(name, arguments)
        if method == "ping":
            return self.ping()
        if method == "initialize":
            return self._legacy_initialize(params)
        if method in _NOTIFICATIONS:
            return _NO_REPLY
        raise MCPError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _check_version(self, params: Mapping[str, Any]) -> None:
        """Reject a request that declares a protocol version we do not serve."""
        declared = request_protocol_version(params)
        if declared is not None and declared not in self.supported_versions:
            raise MCPError(
                UNSUPPORTED_PROTOCOL_VERSION,
                "Unsupported protocol version",
                {"supported": list(self.supported_versions), "requested": declared},
            )

    def _legacy_initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Answer the pre-2026 ``initialize`` handshake for older clients."""
        declared = request_protocol_version(params)
        negotiated = declared if declared in self.supported_versions else self.protocol_version
        payload: dict[str, Any] = {
            "protocolVersion": negotiated,
            "capabilities": self.capabilities(),
            "serverInfo": self.server_info(),
        }
        if self.instructions:
            payload["instructions"] = self.instructions
        return payload

    @staticmethod
    def _normalize_result(raw: Any) -> dict[str, Any]:
        """Coerce a handler's return value into a ``{content, isError}`` result."""
        if isinstance(raw, Mapping) and "content" in raw and "isError" in raw:
            return dict(raw)
        if isinstance(raw, str):
            return text_content(raw)
        return text_content(json.dumps(raw, indent=2, ensure_ascii=False, default=str))

    # -- stdio transport ---------------------------------------------------
    def handle_line(self, line: str) -> str | None:
        """Process one input line; return the response line, or ``None``."""
        stripped = line.strip()
        if not stripped:
            return None
        try:
            request = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return json.dumps(
                jsonrpc_error(None, PARSE_ERROR, f"Parse error: {exc}"),
                ensure_ascii=False,
            )
        response = self.handle_request(request)
        if response is None:
            return None
        return json.dumps(response, ensure_ascii=False)

    def serve(self, instream: IO[str], outstream: IO[str]) -> None:
        """Read newline-delimited requests from ``instream``, write responses."""
        for line in instream:
            response = self.handle_line(line)
            if response is not None:
                outstream.write(response + "\n")
                outstream.flush()

    def run_stdio(self) -> None:
        """Serve over the process' stdin/stdout (the usual stdio transport)."""
        self.serve(sys.stdin, sys.stdout)

    def __repr__(self) -> str:
        return f"<MCPServer name={self.name!r} tools={len(self._tools)}>"


#: Sentinel for "handled, but this is a notification — send nothing".
_NO_REPLY = object()

#: Methods that are notifications by definition (no response is ever sent).
_NOTIFICATIONS: frozenset[str] = frozenset(
    {
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/progress",
        "notifications/roots/list_changed",
    }
)


def _json_type_for(annotation: Any) -> str:
    """Map a Python type annotation onto a JSON-schema primitive type."""
    name = getattr(annotation, "__name__", None)
    if name is None:
        name = str(annotation).split("[", 1)[0].split(".")[-1]
    return _JSON_TYPE_NAMES.get(name, "string")


def schema_from_signature(func: Callable[..., Any]) -> dict[str, Any]:
    """Derive a JSON-schema object from a callable's signature.

    Unknown annotations degrade to ``"string"`` so a tool is always usable.
    """
    signature = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        entry: dict[str, Any] = {"type": _json_type_for(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            entry["default"] = param.default
        properties[param_name] = entry
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def tool_from_callable(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: Mapping[str, Any] | None = None,
) -> Tool:
    """Wrap a plain function as a :class:`Tool` (args expanded as keyword args).

    The schema is derived from the signature unless ``input_schema`` is given;
    unknown keyword arguments are ignored so a stray extra field cannot crash it.
    """
    tool_name = name or str(getattr(func, "__name__", "tool"))
    doc = (inspect.getdoc(func) or "").strip()
    summary = description if description is not None else (doc.splitlines()[0] if doc else "")
    schema = input_schema if input_schema is not None else schema_from_signature(func)
    accepted = set(inspect.signature(func).parameters)

    def handler(arguments: Mapping[str, Any]) -> Any:
        return func(**{key: value for key, value in dict(arguments).items() if key in accepted})

    return Tool(
        name=tool_name,
        handler=handler,
        description=summary,
        input_schema=dict(schema),
    )
