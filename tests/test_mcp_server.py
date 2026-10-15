"""Tests for src.mcp.server — the MCP server, dispatch and stdio loop."""

from __future__ import annotations

import io
import json

import pytest

from src.mcp import protocol as proto
from src.mcp.server import (
    MCPServer,
    Tool,
    schema_from_signature,
    tool_from_callable,
)


def _server_with_echo() -> MCPServer:
    server = MCPServer("test-server", "9.9.9")
    server.register("echo", lambda args: f"echo:{args.get('msg', '')}")
    return server


# ── registration ──────────────────────────────────────────────────────────
def test_register_and_introspection():
    server = _server_with_echo()
    assert server.tool_names() == ["echo"]
    assert len(server.tools) == 1
    assert server.tools[0].name == "echo"
    assert "test-server" in repr(server)


def test_duplicate_registration_raises():
    server = _server_with_echo()
    with pytest.raises(ValueError):
        server.register("echo", lambda a: "x")


def test_add_tool_requires_name():
    with pytest.raises(ValueError):
        Tool(name="", handler=lambda a: "x")
    server = MCPServer()
    with pytest.raises(ValueError):
        server.add_tool(Tool(name="", handler=lambda a: "x"))


def test_remove_tool_is_idempotent():
    server = _server_with_echo()
    server.remove_tool("echo")
    server.remove_tool("echo")
    assert server.tool_names() == []


def test_tool_decorator_returns_handler():
    server = MCPServer()

    @server.tool("greet", description="say hi", input_schema={"type": "object"})
    def greet(args):  # noqa: ANN001, ANN202 - decorator returns the plain fn
        return "hi"

    assert greet({}) == "hi"
    assert server.tool_names() == ["greet"]


# ── MCP surface ───────────────────────────────────────────────────────────
def test_server_info_capabilities_discover():
    server = MCPServer("s", "1", instructions="do things")
    assert server.server_info() == {"name": "s", "version": "1"}
    assert server.capabilities() == {"tools": {"listChanged": False}}
    discovered = server.discover()
    assert discovered["protocolVersion"] == proto.MCP_PROTOCOL_VERSION
    assert discovered["instructions"] == "do things"
    assert discovered["serverInfo"] == {"name": "s", "version": "1"}
    assert proto.META_SERVER_INFO in discovered["_meta"]


def test_discover_without_instructions():
    assert "instructions" not in MCPServer("s", "1").discover()


def test_list_tools_shape_and_cursor_ignored():
    server = _server_with_echo()
    listed = server.list_tools(cursor="page-2")
    assert listed["ttlMs"] == 0
    assert listed["cacheScope"] == "public"
    assert listed["tools"][0]["name"] == "echo"
    assert "inputSchema" in listed["tools"][0]


def test_call_tool_string_result_wrapped_with_meta():
    server = _server_with_echo()
    result = server.call_tool("echo", {"msg": "hi"})
    assert result["isError"] is False
    assert result["content"][0]["text"] == "echo:hi"
    assert proto.META_SERVER_INFO in result["_meta"]


def test_call_tool_passthrough_tool_result():
    server = MCPServer()
    server.register("boom", lambda args: proto.error_content("nope"))
    result = server.call_tool("boom", {})
    assert result["isError"] is True


def test_call_tool_non_string_result_is_json_serialised():
    server = MCPServer()
    server.register("obj", lambda args: {"a": 1})
    result = server.call_tool("obj", {})
    assert json.loads(result["content"][0]["text"]) == {"a": 1}


def test_call_tool_exception_becomes_error_content():
    server = MCPServer()

    def explode(args):  # noqa: ANN001, ANN202
        raise RuntimeError("kaboom")

    server.register("explode", explode)
    result = server.call_tool("explode", {})
    assert result["isError"] is True
    assert "kaboom" in result["content"][0]["text"]


def test_call_tool_mcperror_propagates():
    server = MCPServer()
    server.register("deny", lambda args: (_ for _ in ()).throw(proto.MCPError(proto.INVALID_PARAMS, "no")))
    with pytest.raises(proto.MCPError):
        server.call_tool("deny", {})


def test_call_tool_unknown_raises_method_not_found():
    server = MCPServer()
    with pytest.raises(proto.MCPError) as info:
        server.call_tool("ghost", {})
    assert info.value.code == proto.METHOD_NOT_FOUND


def test_ping():
    assert proto.META_SERVER_INFO in MCPServer("s", "1").ping()["_meta"]


# ── dispatch ──────────────────────────────────────────────────────────────
def _request(method, params=None, req_id=1):
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def test_handle_request_non_mapping():
    response = MCPServer().handle_request(["not", "a", "mapping"])  # type: ignore[arg-type]
    assert response is not None
    assert response["error"]["code"] == proto.INVALID_REQUEST


def test_handle_request_bad_jsonrpc_version():
    response = MCPServer().handle_request({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert response is not None
    assert response["error"]["code"] == proto.INVALID_REQUEST


def test_handle_request_missing_method():
    response = MCPServer().handle_request({"jsonrpc": "2.0", "id": 1})
    assert response is not None
    assert response["error"]["code"] == proto.INVALID_REQUEST


def test_handle_request_dispatches_discover():
    response = MCPServer("s", "1").handle_request(_request("server/discover"))
    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "s"


def test_handle_request_tools_list_supported_version():
    server = _server_with_echo()
    params = {"_meta": {proto.META_PROTOCOL_VERSION: "2026-07-28"}}
    response = server.handle_request(_request("tools/list", params))
    assert response is not None
    assert response["result"]["tools"][0]["name"] == "echo"


def test_handle_request_tools_list_unsupported_version():
    params = {"_meta": {proto.META_PROTOCOL_VERSION: "1900-01-01"}}
    response = MCPServer().handle_request(_request("tools/list", params))
    assert response is not None
    assert response["error"]["code"] == proto.UNSUPPORTED_PROTOCOL_VERSION
    assert response["error"]["data"]["requested"] == "1900-01-01"


def test_handle_request_tools_call_requires_name():
    response = MCPServer().handle_request(_request("tools/call", {"arguments": {}}))
    assert response is not None
    assert response["error"]["code"] == proto.INVALID_PARAMS


def test_handle_request_tools_call_arguments_must_be_object():
    params = {"name": "x", "arguments": "nope"}
    response = MCPServer().handle_request(_request("tools/call", params))
    assert response is not None
    assert response["error"]["code"] == proto.INVALID_PARAMS


def test_handle_request_tools_call_ok():
    response = _server_with_echo().handle_request(
        _request("tools/call", {"name": "echo", "arguments": {"msg": "yo"}})
    )
    assert response is not None
    assert response["result"]["content"][0]["text"] == "echo:yo"


def test_handle_request_ping_and_legacy_initialize():
    server = MCPServer("s", "1")
    assert server.handle_request(_request("ping"))["result"] is not None
    legacy = server.handle_request(_request("initialize", {"protocolVersion": "2025-06-18"}))
    assert legacy["result"]["protocolVersion"] == "2025-06-18"
    unknown_legacy = server.handle_request(_request("initialize", {"protocolVersion": "1999-01-01"}))
    assert unknown_legacy["result"]["protocolVersion"] == server.protocol_version


def test_handle_request_legacy_initialize_carries_instructions():
    server = MCPServer("s", "1", instructions="hi")
    response = server.handle_request(_request("initialize", {}))
    assert response["result"]["instructions"] == "hi"


def test_handle_request_unknown_method_and_notification():
    server = MCPServer()
    response = server.handle_request(_request("does/not/exist", req_id=5))
    assert response["error"]["code"] == proto.METHOD_NOT_FOUND
    assert server.handle_request(_request("does/not/exist", req_id=None)) is None


def test_handle_request_known_notification_returns_none():
    assert MCPServer().handle_request(_request("notifications/initialized", req_id=None)) is None


def test_handle_request_real_method_as_notification_returns_none():
    # a notification that names a real method gets its result, but nothing is sent
    assert MCPServer("s", "1").handle_request({"jsonrpc": "2.0", "method": "ping"}) is None


def test_handle_request_mcperror_from_dispatch_becomes_error():
    server = MCPServer()
    response = server.handle_request(_request("tools/call", {"name": "ghost", "arguments": {}}))
    assert response["error"]["code"] == proto.METHOD_NOT_FOUND


def test_handle_request_internal_error(monkeypatch):
    server = MCPServer("s", "1")

    def boom(name, arguments=None):  # noqa: ANN001, ANN202
        raise RuntimeError("unexpected")

    monkeypatch.setattr(server, "call_tool", boom)
    response = server.handle_request(_request("tools/call", {"name": "x", "arguments": {}}))
    assert response["error"]["code"] == proto.INTERNAL_ERROR


def test_handle_request_internal_error_notification_returns_none(monkeypatch):
    server = MCPServer("s", "1")

    def boom(name, arguments=None):  # noqa: ANN001, ANN202
        raise RuntimeError("unexpected")

    monkeypatch.setattr(server, "call_tool", boom)
    assert server.handle_request({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "x"}}) is None


# ── stdio ─────────────────────────────────────────────────────────────────
def test_handle_line_empty_returns_none():
    assert MCPServer().handle_line("   ") is None


def test_handle_line_bad_json_returns_parse_error():
    line = MCPServer().handle_line("{not json")
    assert line is not None
    assert json.loads(line)["error"]["code"] == proto.PARSE_ERROR


def test_handle_line_valid_and_notification():
    server = MCPServer("s", "1")
    line = server.handle_line(json.dumps(_request("ping")))
    assert line is not None and json.loads(line)["result"] is not None
    notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert server.handle_line(notif) is None


def test_serve_loop():
    instream = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n')
    outstream = io.StringIO()
    MCPServer("s", "1").serve(instream, outstream)
    written = outstream.getvalue().strip()
    assert json.loads(written)["id"] == 1


def test_run_stdio(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"jsonrpc":"2.0","id":9,"method":"ping"}\n'))
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    MCPServer("s", "1").run_stdio()
    assert json.loads(captured.getvalue().strip())["id"] == 9


def test_run_stdio_skips_notifications(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'))
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    MCPServer("s", "1").run_stdio()
    assert captured.getvalue() == ""


# ── schema derivation ─────────────────────────────────────────────────────
def test_schema_from_signature_types_and_required():
    def sample(name: str, count: int = 3, ratio: float = 1.0, flag: bool = False,
               items: list = None, mapping: dict = None, ratio2: object = None):  # noqa: ANN001
        return None

    schema = schema_from_signature(sample)
    props = schema["properties"]
    assert props["name"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["ratio"]["type"] == "number"
    assert props["flag"]["type"] == "boolean"
    assert props["items"]["type"] == "array"
    assert props["mapping"]["type"] == "object"
    assert props["ratio2"]["type"] == "string"  # unknown annotation -> string
    assert schema["required"] == ["name"]
    assert props["count"]["default"] == 3


def test_schema_from_signature_ignores_varargs():
    def sample(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    assert schema_from_signature(sample) == {"type": "object", "properties": {}}


def test_tool_from_callable_name_description_and_dispatch():
    def add(left: int, right: int) -> int:
        """Add two numbers."""
        return left + right

    tool = tool_from_callable(add)
    assert tool.name == "add"
    assert tool.description == "Add two numbers."
    assert tool.spec().input_schema["required"] == ["left", "right"]
    # the handler returns the raw value; the server normalises it to text content
    assert tool.handler({"left": 2, "right": 3, "unexpected": True}) == 5
    server = MCPServer("s", "1")
    server.add_tool(tool)
    assert server.call_tool("add", {"left": 2, "right": 3})["content"][0]["text"] == "5"


def test_tool_from_callable_overrides():
    def original(a: str) -> str:  # noqa: ANN001
        return a

    tool = tool_from_callable(
        original,
        name="renamed",
        description="custom",
        input_schema={"type": "object", "properties": {"a": {"type": "string"}}},
    )
    assert tool.name == "renamed"
    assert tool.description == "custom"
    assert tool.handler({"a": "x"}) == "x"


def test_tool_from_callable_no_docstring():
    tool = tool_from_callable(lambda a=1: a, name="anon")  # noqa: E731
    assert tool.description == ""
