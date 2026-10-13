"""Tests for the legacy novamind MCP server (src/novamind/core/mcp_server.py).

Like tests/test_council.py and tests/test_genome.py, this covers a novamind-layer
module but is standard-library only, so it runs in the phone gate too. The
server is handshake-based (``initialize``); the current-revision server lives in
the first-class ``src.mcp`` package and is tested in tests/test_mcp_*.py.
"""

from __future__ import annotations

import io
import json

from novamind.core.mcp_server import MCP_VERSION, NovaMindMCP, mcp_server


def test_module_has_a_protocol_version_and_singleton():
    assert isinstance(MCP_VERSION, str)
    assert MCP_VERSION
    assert isinstance(mcp_server, NovaMindMCP)


def test_initialize_handshake():
    handshake = NovaMindMCP().initialize({})
    assert handshake["protocolVersion"] == MCP_VERSION
    assert handshake["capabilities"]["tools"]["listChanged"] is False
    assert handshake["serverInfo"]["name"] == "novamind"


def test_list_tools_matches_factory_and_shape():
    server = NovaMindMCP()
    tools = server.list_tools()["tools"]
    assert len(tools) == len(server.factory.list_all())
    assert tools  # never empty
    first = tools[0]
    assert {"name", "description", "inputSchema"} <= set(first)
    assert first["inputSchema"]["required"] == ["code"]
    assert [tool["name"] for tool in tools] == sorted(tool["name"] for tool in tools)


def test_call_tool_unknown_is_error_content():
    result = NovaMindMCP().call_tool("no-such-tool", {})
    assert result["isError"] is True
    assert "Unknown tool" in result["content"][0]["text"]


def test_text_and_error_helpers():
    server = NovaMindMCP()
    assert server._text_content("hi") == {
        "content": [{"type": "text", "text": "hi"}],
        "isError": False,
    }
    assert server._error_content("bad")["isError"] is True


def test_ping():
    assert NovaMindMCP().ping() == {}


def test_handle_request_roundtrip():
    server = NovaMindMCP()
    response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == MCP_VERSION

    tools = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert tools["result"]["tools"]


def test_handle_request_method_not_found_and_notifications():
    server = NovaMindMCP()
    missing = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "bogus/method"})
    assert missing["error"]["code"] == -32601
    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_handle_request_tools_call_unknown_id():
    server = NovaMindMCP()
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "ghost", "arguments": {}}}
    )
    assert response["result"]["isError"] is True


def test_handle_request_internal_error_is_wrapped(monkeypatch):
    server = NovaMindMCP()

    def boom(name, arguments):  # noqa: ANN001, ANN202
        raise RuntimeError("unexpected")

    monkeypatch.setattr(server, "call_tool", boom)
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "x", "arguments": {}}}
    )
    assert response["error"]["code"] == -32603


def test_run_stdio_server_loop(monkeypatch):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"jsonrpc": "2.0", "id": 7, "method": "ping"}\n\n'),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    from novamind.core.mcp_server import run_stdio_server

    run_stdio_server()
    written = captured.getvalue().strip()
    assert json.loads(written)["id"] == 7
