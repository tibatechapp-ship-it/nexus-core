"""Tests for src.mcp.protocol — the MCP wire primitives."""

from __future__ import annotations

import pytest

from src.mcp import protocol as proto


def test_jsonrpc_and_protocol_constants():
    assert proto.JSONRPC_VERSION == "2.0"
    assert proto.MCP_PROTOCOL_VERSION == "2026-07-28"
    assert proto.SUPPORTED_PROTOCOL_VERSIONS[0] == "2026-07-28"
    assert "2024-11-05" in proto.SUPPORTED_PROTOCOL_VERSIONS


def test_meta_keys_follow_spec_prefix():
    assert proto.META_PROTOCOL_VERSION.startswith("io.modelcontextprotocol/")
    assert proto.META_SERVER_INFO.startswith("io.modelcontextprotocol/")


def test_error_codes_values():
    assert proto.PARSE_ERROR == -32700
    assert proto.INVALID_REQUEST == -32600
    assert proto.METHOD_NOT_FOUND == -32601
    assert proto.INVALID_PARAMS == -32602
    assert proto.INTERNAL_ERROR == -32603
    assert proto.UNSUPPORTED_PROTOCOL_VERSION == -32022
    assert proto.MISSING_REQUIRED_CLIENT_CAPABILITY == -32021


def test_text_content_roundtrip():
    block = proto.TextContent("hello")
    assert block.to_dict() == {"type": "text", "text": "hello"}
    assert proto.text_content("hi") == {
        "content": [{"type": "text", "text": "hi"}],
        "isError": False,
    }


def test_error_content_flags_error():
    rendered = proto.error_content("boom")
    assert rendered["isError"] is True
    assert rendered["content"][0]["text"] == "boom"


def test_jsonrpc_result_shape():
    assert proto.jsonrpc_result(7, {"ok": True}) == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"ok": True},
    }


def test_jsonrpc_error_without_and_with_data():
    plain = proto.jsonrpc_error(1, -32601, "nope")
    assert plain["error"] == {"code": -32601, "message": "nope"}
    with_data = proto.jsonrpc_error(2, -32022, "bad version", {"supported": ["x"]})
    assert with_data["error"]["data"] == {"supported": ["x"]}


def test_server_meta():
    meta = proto.server_meta("nexus", "1.2.3")
    assert meta[proto.META_SERVER_INFO] == {"name": "nexus", "version": "1.2.3"}


def test_mcp_error_attributes_and_to_error():
    err = proto.MCPError(proto.INVALID_PARAMS, "bad", {"field": "x"})
    assert err.code == proto.INVALID_PARAMS
    assert str(err) == "bad"
    assert err.to_error() == {"code": proto.INVALID_PARAMS, "message": "bad", "data": {"field": "x"}}


def test_mcp_error_to_error_without_data():
    err = proto.MCPError(proto.METHOD_NOT_FOUND, "missing")
    assert err.to_error() == {"code": proto.METHOD_NOT_FOUND, "message": "missing"}


def test_tool_spec_requires_name():
    with pytest.raises(ValueError):
        proto.ToolSpec(name="")


def test_tool_spec_to_dict_minimal_and_with_title():
    minimal = proto.ToolSpec(name="echo")
    assert minimal.to_dict() == {
        "name": "echo",
        "description": "",
        "inputSchema": {},
    }
    titled = proto.ToolSpec(name="echo", description="d", title="Echo", input_schema={"type": "object"})
    assert titled.to_dict()["title"] == "Echo"
    assert titled.to_dict()["inputSchema"] == {"type": "object"}


def test_request_protocol_version_prefers_meta():
    params = {"_meta": {proto.META_PROTOCOL_VERSION: "2026-07-28"}}
    assert proto.request_protocol_version(params) == "2026-07-28"


def test_request_protocol_version_legacy_top_level():
    assert proto.request_protocol_version({"protocolVersion": "2025-06-18"}) == "2025-06-18"


def test_request_protocol_version_absent_and_malformed():
    assert proto.request_protocol_version({}) is None
    assert proto.request_protocol_version({"_meta": "not-a-mapping"}) is None
    assert proto.request_protocol_version({"_meta": {proto.META_PROTOCOL_VERSION: 5}}) is None


def test_request_client_info():
    info = {"name": "cli", "version": "1"}
    assert proto.request_client_info({"_meta": {proto.META_CLIENT_INFO: info}}) == info
    assert proto.request_client_info({}) is None
    assert proto.request_client_info({"_meta": {proto.META_CLIENT_INFO: "nope"}}) is None
