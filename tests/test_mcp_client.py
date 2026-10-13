"""Tests for src.mcp.client — in-process + stdio clients and the schema bridge."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.mcp.client import (
    InProcessClient,
    MCPClientError,
    StdioClient,
    content_text,
    default_server_command,
    to_tool_schemas,
)
from src.mcp.protocol import METHOD_NOT_FOUND
from src.mcp.server import MCPServer

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(SRC)])}

_INLINE_SERVER = (
    "from src.mcp.server import MCPServer\n"
    "s = MCPServer('inline', '1')\n"
    "s.register('echo', lambda a: 'echo:' + str(a.get('msg', '')),"
    " input_schema={'type': 'object', 'properties': {'msg': {'type': 'string'}},"
    " 'required': ['msg']})\n"
    "s.run_stdio()\n"
)


def _inline(command_source: str) -> list[str]:
    return [sys.executable, "-c", command_source]


# ── helpers ───────────────────────────────────────────────────────────────
def test_content_text_joins_text_blocks():
    result = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    assert content_text(result) == "a\nb"


def test_content_text_tolerates_junk():
    assert content_text({}) == ""
    assert content_text({"content": "not-a-list"}) == ""
    assert content_text({"content": [{"type": "image", "data": "x"}, "junk"]}) == ""
    assert content_text({"content": [{"type": "text", "text": 5}]}) == ""


def test_mcp_client_error_attributes():
    err = MCPClientError("broken", code=-1, data={"x": 1})
    assert str(err) == "broken"
    assert err.code == -1
    assert err.data == {"x": 1}


# ── InProcessClient ───────────────────────────────────────────────────────
def _example_server() -> MCPServer:
    server = MCPServer("inproc", "2")
    server.register("echo", lambda args: f"echo:{args.get('msg', '')}")
    return server


def test_inprocess_roundtrip():
    client = InProcessClient(_example_server())
    assert client.discover()["serverInfo"]["name"] == "inproc"
    tools = client.list_tools()
    assert [t["name"] for t in tools] == ["echo"]
    assert client.call_tool("echo", {"msg": "hi"}) == "echo:hi"


def test_inprocess_raises_client_error_on_server_error():
    client = InProcessClient(_example_server())
    with pytest.raises(MCPClientError) as info:
        client.call_tool("ghost", {})
    assert info.value.code == METHOD_NOT_FOUND


def test_inprocess_error_code_not_int_becomes_none():
    class _BadCodeServer:
        def handle_request(self, message):  # noqa: ANN001, ANN202
            return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": "x", "message": "m"}}

    with pytest.raises(MCPClientError) as info:
        InProcessClient(_BadCodeServer()).request("ping")
    assert info.value.code is None


def test_inprocess_no_response_raises():
    class _NullServer:
        def handle_request(self, message):  # noqa: ANN001, ANN202
            return None

    with pytest.raises(MCPClientError):
        InProcessClient(_NullServer()).request("ping")


def test_inprocess_coerces_non_mapping_results():
    class _WeirdServer:
        def handle_request(self, message):  # noqa: ANN001, ANN202
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": "scalar"}

    client = InProcessClient(_WeirdServer())
    assert client.discover() == {}
    assert client.list_tools() == []
    assert client.call_tool("echo", {}) == ""


def test_inprocess_list_tools_ignores_non_list():
    class _Server:
        def handle_request(self, message):  # noqa: ANN001, ANN202
            result = {"tools": "nope"}
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}

    assert InProcessClient(_Server()).list_tools() == []


# ── StdioClient ───────────────────────────────────────────────────────────
def test_stdio_requires_command():
    with pytest.raises(ValueError):
        StdioClient([])


def test_stdio_end_to_end():
    client = StdioClient(_inline(_INLINE_SERVER), env=ENV, cwd=str(ROOT))
    with client as running:
        assert running.running is True
        assert [t["name"] for t in client.list_tools()] == ["echo"]
        assert client.call_tool("echo", {"msg": "yo"}) == "echo:yo"
    assert client.running is False


def test_stdio_start_is_idempotent():
    client = StdioClient(_inline(_INLINE_SERVER), env=ENV, cwd=str(ROOT))
    client.start()
    first = client._proc
    client.start()
    assert client._proc is first
    client.close()


def test_stdio_respawns_after_close():
    client = StdioClient(_inline(_INLINE_SERVER), env=ENV, cwd=str(ROOT))
    client.start()
    client.close()
    assert client.running is False
    assert client.call_tool("echo", {"msg": "again"}) == "echo:again"
    client.close()
    client.close()  # close is safe to call twice


def test_stdio_server_error_raises_client_error():
    client = StdioClient(_inline(_INLINE_SERVER), env=ENV, cwd=str(ROOT))
    with pytest.raises(MCPClientError) as info:
        client.call_tool("ghost", {})
    assert info.value.code == METHOD_NOT_FOUND
    client.close()


def test_stdio_invalid_json_raises():
    script = "import sys\nsys.stdin.readline()\nprint('not json')\n"
    client = StdioClient(_inline(script), env=ENV, cwd=str(ROOT))
    with pytest.raises(MCPClientError):
        client.request("ping")
    client.close()


def test_stdio_closed_connection_raises():
    script = "import sys\nsys.stdin.readline()\n"
    client = StdioClient(_inline(script), env=ENV, cwd=str(ROOT))
    with pytest.raises(MCPClientError):
        client.request("ping")
    client.close()


def test_stdio_non_object_response_raises():
    script = "import sys\nsys.stdin.readline()\nprint('[1, 2, 3]')\n"
    client = StdioClient(_inline(script), env=ENV, cwd=str(ROOT))
    with pytest.raises(MCPClientError):
        client.request("ping")
    client.close()


def test_stdio_list_tools_and_call_tool_ignore_non_mapping():
    script = (
        "import sys, json\n"
        "sys.stdin.readline()\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': 'scalar'}))\n"
    )
    client = StdioClient(_inline(script), env=ENV, cwd=str(ROOT))
    assert client.list_tools() == []
    client.close()


def test_stdio_list_tools_ignores_non_list_tools():
    script = (
        "import sys, json\n"
        "sys.stdin.readline()\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'tools': 'nope'}}))\n"
    )
    client = StdioClient(_inline(script), env=ENV, cwd=str(ROOT))
    assert client.list_tools() == []
    client.close()


# ── schema bridge ─────────────────────────────────────────────────────────
def test_to_tool_schemas_maps_types_and_required():
    tools = [
        {
            "name": "search",
            "description": "find things",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "the query"},
                    "limit": {"type": "integer"},
                    "weird": {"type": "null"},
                },
                "required": ["query"],
            },
        }
    ]
    schemas = to_tool_schemas(tools, prefix="mcp_")
    assert len(schemas) == 1
    schema = schemas[0]
    assert schema.name == "mcp_search"
    assert schema.description == "find things"
    params = {p.name: p for p in schema.parameters}
    assert params["query"].type == "string"
    assert params["query"].required is True
    assert params["limit"].type == "integer"
    assert params["limit"].required is False
    assert params["weird"].type == "string"  # invalid primitive -> fallback


def test_to_tool_schemas_skips_invalid_entries():
    tools = [
        {"description": "no name"},
        {"name": "", "inputSchema": "bad"},
        {"name": "ok", "inputSchema": {"required": "not-a-list", "properties": "bad"}},
    ]
    schemas = to_tool_schemas(tools)
    assert [s.name for s in schemas] == ["ok"]
    assert schemas[0].parameters == ()


def test_default_server_command():
    command = default_server_command()
    assert command == [sys.executable, "-m", "src.mcp"]
