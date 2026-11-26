"""Tests for the external MCP adapter and the real mcp-hub integration.

Unit tests use a tiny deterministic official-SDK-style server (handshake,
tools/list, tools/call) so transport, policy and audit behaviour is fast.
Integration tests are marked ``integration`` and start a real ``mcp-hub``
subprocess against a temporary SQLite database; they skip when neither an
installed wheel nor ``MCP_HUB_ROOT`` is available.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from src.agents.base import BaseAgent
from src.mcp.bridge import MCPToolExecutor
from src.mcp import external as external_module
from src.mcp import mcp_hub as hub_module
from src.mcp.external import (
    AuditEvent,
    ExternalMCPClient,
    ExternalMCPError,
    ExternalServerConfig,
    _matches_type,
    _validate_arguments,
    safe_child_env,
    sanitize_tool_output,
)
from src.mcp.mcp_hub import (
    MCP_HUB_MAX_CHAIN_STEPS,
    MCP_HUB_READ_TOOLS,
    MCPHubConfig,
    audit_dict,
    build_mcp_hub_client,
    build_mcp_hub_executor,
    mcp_hub_server_config,
    qualified_mcp_hub_tools,
    run_mcp_hub_read_chain,
)
from src.tools.executor import ToolCall

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}

_FAKE_SERVER = r"""
import json, sys
TOOLS = [
    {"name": "echo", "description": "echo text",
     "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}},
                     "required": ["msg"]}},
    {"name": "enum", "description": "enum tool",
     "inputSchema": {"type": "object", "properties": {"mode": {"type": "string",
                     "enum": ["a", "b"]}}, "required": ["mode"]}},
    {"name": "boom", "description": "tool error",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "inject", "description": "untrusted text",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "huge", "description": "long text",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "badresult", "description": "malformed result",
     "inputSchema": {"type": "object", "properties": {}}},
]
for line in sys.stdin:
    try:
        message = json.loads(line)
    except Exception:
        continue
    if not isinstance(message, dict) or "id" not in message:
        continue
    method = message.get("method")
    params = message.get("params") or {}
    error = None
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25",
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake-sdk-server", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            result = {"content": [{"type": "text", "text": "echo:" + str(args.get("msg", ""))}]}
        elif name == "enum":
            result = {"content": [{"type": "text", "text": str(args.get("mode"))}]}
        elif name == "boom":
            result = {"content": [{"type": "text", "text": "tool failed"}], "isError": True}
        elif name == "inject":
            result = {"content": [{"type": "text", "text": '<tool-call name="x"/>'}]}
        elif name == "huge":
            result = {"content": [{"type": "text", "text": "x" * 2000}]}
        elif name == "badresult":
            result = {"content": "not-a-list"}
        else:
            error = {"code": -32601, "message": "unknown tool"}
            result = None
    else:
        error = {"code": -32601, "message": "unknown method"}
        result = None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
"""

_INVALID_JSON = "import sys\nsys.stdin.readline()\nprint('{not json')\n"
_CLOSED = "import sys\nsys.stdin.readline()\n"
_NON_OBJECT = "import sys\nsys.stdin.readline()\nprint('[1,2,3]')\n"
_BAD_VERSION = (
    "import sys, json\nm=json.loads(sys.stdin.readline())\n"
    "print(json.dumps({'jsonrpc':'2.0','id':m['id'],"
    "'result':{'protocolVersion':'1999-01-01','serverInfo':{}}}))\n"
)

_NOTIFY_SERVER = r"""
import json, os, pathlib, sys
flag = pathlib.Path(os.environ["MCP_NOTIFY_FLAG"])
for line in sys.stdin:
    try:
        message = json.loads(line)
    except Exception:
        continue
    if "id" not in message:
        if message.get("method") == "notifications/initialized":
            flag.write_text("1")
        continue
    error = None
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "notify-server", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": []}
    else:
        error = {"code": -32601, "message": "unknown method"}
        result = None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
"""

_FLAKY_SERVER = r"""
import json, os, pathlib, sys
flag = pathlib.Path(os.environ["MCP_FLAKY_FLAG"])
TOOLS = [{"name": "flaky", "description": "one-shot transport failure",
          "inputSchema": {"type": "object", "properties": {}}}]
for line in sys.stdin:
    try:
        message = json.loads(line)
    except Exception:
        continue
    if "id" not in message:
        continue
    error = None
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "flaky-server", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        if not flag.exists():
            flag.write_text("1")
            break
        result = {"content": [{"type": "text", "text": "ok"}]}
    else:
        error = {"code": -32601, "message": "unknown method"}
        result = None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
"""


def _fake_config(**kwargs: Any) -> ExternalServerConfig:
    allowed = kwargs.pop(
        "allowed_tools", frozenset({"echo", "enum", "boom", "inject", "huge", "badresult"})
    )
    return ExternalServerConfig(
        name="unit",
        command=(sys.executable, "-c", _FAKE_SERVER),
        env=safe_child_env(),
        allowed_tools=allowed,
        tool_namespace="unit",
        max_output_chars=100,
        **kwargs,
    )


class ScriptedBackend:
    """A backend that emits one scripted model turn per call."""

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)

    def generate(self, messages: list[Any], *, model: str | None = None) -> str:
        if not self.outputs:
            raise AssertionError("backend was called more often than scripted")
        return self.outputs.pop(0)


class HubAgent(BaseAgent):
    name = "hub-agent"
    tools = ("mcp_hub.search_servers",)


# ── unit: policy helpers ───────────────────────────────────────────────────
def test_config_validation():
    with pytest.raises(ValueError):
        ExternalServerConfig(name="bad name", command=(sys.executable,))
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=())
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=(sys.executable,), protocol_version="nope")
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=(sys.executable,), timeout_s=0)
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=(sys.executable,), max_tools=0)
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=(sys.executable,), tool_namespace="bad-name")
    with pytest.raises(ValueError):
        ExternalServerConfig(
            name="ok",
            command=(sys.executable,),
            allowed_tools=frozenset({1}),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=(sys.executable,), env={"lower": "x"})
    with pytest.raises(ValueError):
        ExternalServerConfig(name="ok", command=(sys.executable,), env={"BAD": "a\nb"})


def test_safe_child_env_filters_parent(monkeypatch):
    monkeypatch.setenv("SHOULD_NOT_LEAK", "parent-value")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = safe_child_env({"MCP_HUB_DB": "/tmp/hub.sqlite3"})
    assert "SHOULD_NOT_LEAK" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["MCP_HUB_DB"] == "/tmp/hub.sqlite3"
    with pytest.raises(ValueError):
        safe_child_env({"bad-key": "x"})
    with pytest.raises(ValueError):
        safe_child_env({"KEY": "bad\nvalue"})
    with pytest.raises(ValueError):
        safe_child_env({"KEY": "x" * 4097})


def test_sanitize_output_and_schema_validation():
    assert "&lt;tool-call" in sanitize_tool_output('<tool-call name="x"/>')
    assert "&lt;system" in sanitize_tool_output("<system>hi</system>")
    assert "&lt;|im_start|>" in sanitize_tool_output("<|im_start|>")
    spec = {
        "inputSchema": {
            "type": "object",
            "properties": {"msg": {"type": "string"}, "mode": {"type": "string", "enum": ["a"]}},
            "required": ["msg"],
        }
    }
    assert _validate_arguments(spec, {}) == "missing required parameter 'msg'"
    assert _validate_arguments(spec, {"msg": "x", "extra": 1}) == "unknown parameter 'extra'"
    assert _validate_arguments(spec, {"msg": 1}) == "parameter 'msg' must be string"
    assert _validate_arguments(spec, {"msg": "x", "mode": "z"}) is not None
    assert _validate_arguments(spec, {"msg": "x" * 20_000}) is not None
    assert _validate_arguments({}, {"anything": 1}) is None
    bounded = {
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}},
        }
    }
    assert _validate_arguments(bounded, {"limit": 5}) is None
    assert _validate_arguments(bounded, {"limit": 0}) == "parameter 'limit' must be >= 1"
    assert _validate_arguments(bounded, {"limit": 201}) == "parameter 'limit' must be <= 200"


# ── unit: transport round trips ────────────────────────────────────────────
def test_external_handshake_discovery_and_calls():
    events: list[dict[str, Any]] = []
    with ExternalMCPClient(
        _fake_config(), on_audit=lambda event: events.append(event.to_dict())
    ) as client:
        assert client.running is True
        names = client.tool_names()
        assert client.protocol_version == "2025-11-25"
        assert client.server_info["name"] == "fake-sdk-server"
        assert names[0] == "echo"
        schemas = client.tool_schemas(prefix="unit.")
        assert schemas[0].name == "unit.echo"
        assert client.call_tool("unit.echo", {"msg": "hi"}) == "echo:hi"
        assert "&lt;tool-call" in client.call_tool("inject", {})
        assert client.call_tool("enum", {"mode": "a"}) == "a"
        long_output = client.call_tool("huge", {})
        assert len(long_output) <= 130
        assert "truncated" in long_output
    assert client.running is False
    assert len(events) == 4
    assert all("output" not in event and "arguments" not in event for event in events)


def test_external_policy_and_error_paths():
    config = _fake_config(allowed_tools=frozenset({"echo"}))
    client = ExternalMCPClient(config)
    try:
        assert client.tool_names() == ["echo"]
        with pytest.raises(ExternalMCPError) as denied:
            client.call_tool("unit.boom", {})
        assert denied.value.code == -32001
        with pytest.raises(ExternalMCPError) as invalid:
            client.call_tool("unit.echo", {"wrong": 1})
        assert invalid.value.code == -32602
        with pytest.raises(ExternalMCPError):
            client.call_tool("", {})
    finally:
        client.close()

    open_client = ExternalMCPClient(_fake_config(allowed_tools=None))
    try:
        with pytest.raises(ExternalMCPError) as unknown:
            open_client.call_tool("unit.ghost", {})
        assert unknown.value.code == -32601
    finally:
        open_client.close()


def test_external_reports_tool_and_transport_errors():
    client = ExternalMCPClient(_fake_config())
    try:
        with pytest.raises(ExternalMCPError):
            client.call_tool("boom", {})
        with pytest.raises(ExternalMCPError) as bad:
            client.call_tool("badresult", {})
        assert bad.value.code == -32603
    finally:
        client.close()

    for script in (_INVALID_JSON, _CLOSED, _NON_OBJECT, _BAD_VERSION):
        broken = ExternalServerConfig(
            name="broken",
            command=(sys.executable, "-c", script),
            env=safe_child_env(),
        )
        other = ExternalMCPClient(broken)
        try:
            with pytest.raises(ExternalMCPError):
                other.list_tools()
        finally:
            other.close()


def test_external_reconnect_budget_and_spawn_failure():
    client = ExternalMCPClient(_fake_config(max_reconnects=0))
    client.start()
    proc = client._proc
    assert proc is not None
    proc.terminate()
    proc.wait(timeout=5)
    with pytest.raises(ExternalMCPError) as exhausted:
        client.call_tool("echo", {"msg": "again"})
    assert "reconnect budget" in str(exhausted.value)
    client.close()

    missing = ExternalServerConfig(
        name="missing", command=("definitely-not-a-real-mcp-binary",), env=safe_child_env()
    )
    with pytest.raises(ExternalMCPError):
        ExternalMCPClient(missing).start()


def test_retry_config_is_bounded():
    with pytest.raises(ValueError):
        ExternalServerConfig(name="unit", command=(sys.executable,), max_call_retries=3)
    with pytest.raises(ValueError):
        ExternalServerConfig(
            name="unit", command=(sys.executable,), retry_safe_tools=frozenset({""})
        )
    with pytest.raises(ValueError):
        ExternalServerConfig(
            name="unit",
            command=(sys.executable,),
            argument_limits={"": {"limit": {"maximum": 1}}},  # type: ignore[list-item]
        )
    with pytest.raises(ValueError):
        ExternalServerConfig(
            name="unit",
            command=(sys.executable,),
            argument_limits={"echo": {"limit": {"maximum": "many"}}},  # type: ignore[dict-item]
        )
    config = ExternalServerConfig(
        name="unit",
        command=(sys.executable,),
        max_call_retries=1,
        retry_safe_tools=frozenset({"x"}),
    )
    assert config.max_call_retries == 1
    assert config.retry_safe_tools == frozenset({"x"})


def test_initialized_notification_is_sent(tmp_path):
    marker = tmp_path / "initialized"
    config = ExternalServerConfig(
        name="unit",
        command=(sys.executable, "-c", _NOTIFY_SERVER),
        env=safe_child_env({"MCP_NOTIFY_FLAG": str(marker)}),
        allowed_tools=frozenset(),
        tool_namespace="unit",
    )
    client = ExternalMCPClient(config)
    try:
        assert client.tool_names() == []
        assert marker.read_text() == "1"
        assert client.protocol_version == "2025-11-25"
        assert client.server_info["name"] == "notify-server"
    finally:
        client.close()


def test_readonly_transport_retry_is_bounded_and_content_free(tmp_path):
    flag = tmp_path / "flaky"
    env = safe_child_env({"MCP_FLAKY_FLAG": str(flag)})

    def config(**kwargs: Any) -> ExternalServerConfig:
        return ExternalServerConfig(
            name="unit",
            command=(sys.executable, "-c", _FLAKY_SERVER),
            env=env,
            allowed_tools=frozenset({"flaky"}),
            tool_namespace="unit",
            **kwargs,
        )

    events: list[dict[str, Any]] = []
    client = ExternalMCPClient(
        config(
            max_call_retries=1,
            retry_safe_tools=frozenset({"flaky"}),
        ),
        on_audit=lambda event: events.append(event.to_dict()),
    )
    try:
        assert client.call_tool("unit.flaky", {}) == "ok"
        assert flag.exists()
        assert len(events) == 1
        assert events[0]["ok"] is True
        assert all("arguments" not in e and "output" not in e for e in events)
    finally:
        client.close()

    flag.unlink()
    denied_events: list[dict[str, Any]] = []
    no_retry = ExternalMCPClient(
        config(max_call_retries=1, retry_safe_tools=frozenset()),
        on_audit=lambda event: denied_events.append(event.to_dict()),
    )
    try:
        with pytest.raises(ExternalMCPError) as error:
            no_retry.call_tool("flaky", {})
        assert "closed the connection" in str(error.value)
        assert len(denied_events) == 1
        assert denied_events[0]["ok"] is False
    finally:
        no_retry.close()


# ── mcp-hub policy configuration ───────────────────────────────────────────
def test_mcp_hub_config_and_environment():
    config = MCPHubConfig(db_path="hub.sqlite3", allowed_tools=frozenset({"search_servers"}))
    assert config.allowed_tools == frozenset({"search_servers"})
    rendered = qualified_mcp_hub_tools(config.allowed_tools)
    assert rendered == frozenset({"mcp_hub.search_servers"})
    server = mcp_hub_server_config(config)
    assert server.name == "mcp_hub"
    assert server.tool_namespace == "mcp_hub"
    assert server.command[1:] == ("-m", "mcp_hub.mcp_server")
    assert server.argument_limits["query_catalog"]["limit"]["maximum"] == 200
    assert server.retry_safe_tools == frozenset({"search_servers"})
    assert set(server.env) == {"MCP_HUB_DB"}
    assert "SHOULD_NOT_LEAK" not in server.env
    with pytest.raises(ValueError):
        MCPHubConfig(allowed_tools=frozenset({"write_file"}))
    with pytest.raises(ValueError):
        MCPHubConfig(db_path="")
    assert MCPHubConfig("hub.sqlite3", pythonpath="/trusted/source").pythonpath == "/trusted/source"


def test_read_chain_validation_is_fail_closed():
    config = MCPHubConfig("hub.sqlite3", allowed_tools=frozenset({"search_servers"}))
    with pytest.raises(ValueError, match=r"1\.\.5"):
        run_mcp_hub_read_chain([], config=config)
    with pytest.raises(ValueError, match=r"1\.\.5"):
        run_mcp_hub_read_chain(
            [("search_servers", {})] * (MCP_HUB_MAX_CHAIN_STEPS + 1), config=config
        )
    with pytest.raises(ValueError, match="not permitted"):
        run_mcp_hub_read_chain([("get_server", {"server_id": 1})], config=config)
    with pytest.raises(ValueError, match="within the mcp-hub read-only allowlist"):
        run_mcp_hub_read_chain(
            [("search_servers", {})],
            config=config,
            allowed_tools=frozenset({"search_servers", "get_server"}),
        )
    with pytest.raises(ValueError, match="mapping or a callable"):
        run_mcp_hub_read_chain([("search_servers", "bad")], config=config)


# ── real process integration ───────────────────────────────────────────────
def _hub_root() -> str | None:
    configured = os.environ.get("MCP_HUB_ROOT")
    if not configured or not Path(configured).is_dir():
        return None
    source = Path(configured) / "src"
    return str(source if (source / "mcp_hub").is_dir() else configured)


@pytest.mark.integration
def test_real_mcp_hub_agent_call_and_permissions(tmp_path):
    pytest.importorskip("mcp")
    pytest.importorskip("mcp_hub")
    from mcp_hub.database import Catalog
    from mcp_hub.models import Server

    db = tmp_path / "hub.sqlite3"
    catalog = Catalog(str(db))
    catalog.add_server(
        Server(
            name="alpha-mcp-server",
            description="seed server for integration test",
            categories="search",
            source="test",
        )
    )
    config = MCPHubConfig(db_path=db, pythonpath=_hub_root())
    events: list[dict[str, Any]] = []
    client = build_mcp_hub_client(config, on_audit=lambda event: events.append(event.to_dict()))
    try:
        assert client.server_info["name"] == "mcp-hub"
        assert client.protocol_version == "2025-11-25"
        tools = client.tool_names()
        assert set(tools) == set(MCP_HUB_READ_TOOLS)
        direct = client.call_tool("mcp_hub.search_servers", {"query": "alpha"})
        assert "alpha-mcp-server" in direct
    finally:
        client.close()

    executor = build_mcp_hub_executor(config)
    try:
        agent = HubAgent(
            ScriptedBackend(
                '<tool-call name="mcp_hub.search_servers" args=\'{"query":"alpha"}\'/>',
                "found it",
            )
        )
        run = executor.run(agent, "find alpha")
        assert run.result.ok is True
        assert run.outcomes[0].ok is True
        assert "alpha-mcp-server" in run.outcomes[0].output
        assert run.result.output == "found it"

        denied = executor.execute(
            ToolCall("mcp_hub.get_server", {"server_id": 1}),
            allowed_tools=frozenset({"mcp_hub.search_servers"}),
        )
        assert denied.ok is False
        assert "not permitted" in (denied.error or "")
    finally:
        executor.client.close()

    assert events
    assert all("arguments" not in event and "output" not in event for event in events)


@pytest.mark.integration
def test_real_mcp_hub_extra_read_tool_and_schema_limits(tmp_path):
    pytest.importorskip("mcp")
    pytest.importorskip("mcp_hub")

    config = MCPHubConfig(db_path=tmp_path / "catalog.sqlite3", pythonpath=_hub_root())
    events: list[dict[str, Any]] = []
    executor = build_mcp_hub_executor(config, on_audit=lambda event: events.append(event.to_dict()))
    try:
        schemas = {schema.name: schema for schema in executor.tool_schemas(prefix="")}
        assert "query_catalog" in schemas

        ok = executor.execute(
            ToolCall("mcp_hub.query_catalog", {"kind": "server", "category": "arabic", "limit": 5})
        )
        assert ok.ok is True
        payload = json.loads(ok.output or "{}")
        assert payload["count"] >= 1
        assert all(row["category"] == "arabic" for row in payload["results"])

        bad = executor.execute(ToolCall("mcp_hub.query_catalog", {"kind": "server", "limit": 201}))
        assert bad.ok is False
        assert "must be <=" in (bad.error or "")
        with pytest.raises(ExternalMCPError) as invalid:
            executor.client.call_tool("mcp_hub.query_catalog", {"limit": 201})
        assert invalid.value.code == -32602
    finally:
        executor.client.close()

    assert events
    assert any(event["tool"] == "query_catalog" and event["ok"] is False for event in events)
    assert all("arguments" not in event and "output" not in event for event in events)


@pytest.mark.integration
def test_real_mcp_hub_read_chain_with_context_and_fail_fast(tmp_path):
    pytest.importorskip("mcp")
    pytest.importorskip("mcp_hub")
    from mcp_hub.database import Catalog
    from mcp_hub.models import Server

    db = tmp_path / "chain.sqlite3"
    catalog = Catalog(str(db))
    catalog.add_server(
        Server(
            name="alpha-mcp-server",
            description="seed server for chained integration test",
            categories="search",
            source="test",
        )
    )
    config = MCPHubConfig(
        db_path=db,
        pythonpath=_hub_root(),
        allowed_tools=frozenset({"list_categories", "servers_by_category", "get_server"}),
    )

    def rows(text: str) -> list[dict[str, Any]]:
        parsed: Any = json.loads(text)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        raise AssertionError(f"unexpected rows payload: {type(parsed).__name__}")

    def category_args(previous: tuple[str, ...]) -> dict[str, Any]:
        row = next(item for item in rows(previous[-1]) if item["category"] == "search")
        return {"category": row["category"], "limit": 1}

    def server_args(previous: tuple[str, ...]) -> dict[str, Any]:
        return {"server_id": int(rows(previous[-1])[0]["id"])}

    events: list[dict[str, Any]] = []
    outputs = run_mcp_hub_read_chain(
        [
            ("mcp_hub.list_categories", {}),
            ("mcp_hub.servers_by_category", category_args),
            ("mcp_hub.get_server", server_args),
        ],
        config=config,
        on_audit=lambda event: events.append(event.to_dict()),
    )
    assert len(outputs) == 3
    assert any(item["category"] == "search" for item in rows(outputs[0]))
    assert rows(outputs[1])[0]["name"] == "alpha-mcp-server"
    assert json.loads(outputs[2])["name"] == "alpha-mcp-server"
    assert [event["tool"] for event in events] == [
        "list_categories",
        "servers_by_category",
        "get_server",
    ]
    assert all("arguments" not in event and "output" not in event for event in events)

    failure_events: list[dict[str, Any]] = []
    with pytest.raises(ExternalMCPError) as failure:
        run_mcp_hub_read_chain(
            [("get_server", {"server_id": 999_999})],
            config=config,
            on_audit=lambda event: failure_events.append(event.to_dict()),
        )
    assert failure.value.code == -32021
    assert failure.value.data == {"step": 1, "tool": "get_server"}
    assert failure_events
    assert all(event["ok"] is False for event in failure_events)
    assert all("arguments" not in event and "output" not in event for event in failure_events)


@pytest.mark.integration
def test_real_mcp_hub_reconnect_and_failure(tmp_path):
    pytest.importorskip("mcp")
    pytest.importorskip("mcp_hub")
    config = MCPHubConfig(
        db_path=tmp_path / "hub.sqlite3", pythonpath=_hub_root(), max_reconnects=1
    )
    client = build_mcp_hub_client(config)
    try:
        proc = client._proc
        assert proc is not None
        proc.terminate()
        proc.wait(timeout=5)
        output = client.call_tool("doctor_report", {})
        assert isinstance(output, str) and output
    finally:
        client.close()

    fragile = MCPHubConfig(
        db_path=tmp_path / "fragile.sqlite3",
        pythonpath=_hub_root(),
        max_reconnects=0,
    )
    client = build_mcp_hub_client(fragile)
    try:
        proc = client._proc
        assert proc is not None
        proc.terminate()
        proc.wait(timeout=5)
        with pytest.raises(ExternalMCPError) as error:
            client.call_tool("doctor_report", {})
        assert "reconnect budget" in str(error.value)
    finally:
        client.close()


# ── unit: defensive edges on the sensitive transport code ────────────────────
def test_json_schema_type_helper_and_reader_defensive_paths():
    assert _matches_type(True, "boolean") is True
    assert _matches_type(1, "integer") is True
    assert _matches_type(True, "integer") is False
    assert _matches_type(1.5, "number") is True
    assert _matches_type(True, "number") is False
    assert _matches_type([], "array") is True
    assert _matches_type({}, "object") is True
    assert _matches_type("x", "whatever") is True

    oversize = ExternalMCPClient(_fake_config(max_response_bytes=512))
    oversize._reader(io.BytesIO(b"\n" + b"x" * 1000 + b"\n"))
    assert oversize._fatal is not None
    assert "byte limit" in str(oversize._fatal)
    oversize.close()

    class BrokenStream:
        def readline(self) -> bytes:
            raise OSError("read failed")

    broken = ExternalMCPClient(_fake_config())
    broken._reader(BrokenStream())  # type: ignore[arg-type]
    assert broken._fatal is not None
    assert "stdio read failed" in str(broken._fatal)
    broken.close()


def test_transport_limits_and_closed_lifecycle():
    client = ExternalMCPClient(_fake_config(max_response_bytes=512))
    with pytest.raises(ExternalMCPError) as limit:
        client._raw_request("ping", {"blob": "x" * 900})
    assert "request exceeds" in str(limit.value)
    with pytest.raises(ExternalMCPError) as no_proc:
        client._send_notification("notifications/test")
    assert "not available" in str(no_proc.value)

    client.start()
    client.start()  # idempotent while alive
    assert client.running is True
    client.close()
    with pytest.raises(ExternalMCPError) as closed:
        client.start()
    assert "closed" in str(closed.value)
    with pytest.raises(ExternalMCPError) as closed_call:
        client.call_tool("echo", {"msg": "x"})
    assert "closed" in str(closed_call.value)

    fatal = ExternalMCPClient(_fake_config())
    fatal._fatal = ExternalMCPError("pre-existing failure")
    with pytest.raises(ExternalMCPError):
        fatal.start()
    fatal.close()


def test_raw_request_error_shapes_timeouts_and_write_failures():
    client = ExternalMCPClient(_fake_config(timeout_s=0.3))
    client.start()
    client._next_id = 0
    client._queue.put({"jsonrpc": "2.0", "id": 999, "result": {"ignored": True}})
    client._queue.put({"jsonrpc": "2.0", "id": 1, "error": {"code": "bad", "message": "bad code"}})
    with pytest.raises(ExternalMCPError) as error:
        client._raw_request("initialize", {"protocolVersion": "2025-11-25"})
    assert error.value.code is None
    assert "bad code" in str(error.value)
    client.close()

    silent = ExternalServerConfig(
        name="silent",
        command=(sys.executable, "-c", "import sys,time; sys.stdin.readline(); time.sleep(2)"),
        env=safe_child_env(),
        timeout_s=0.2,
    )
    slow = ExternalMCPClient(silent)
    with pytest.raises(ExternalMCPError) as timeout:
        slow.list_tools()
    assert "timeout" in str(timeout.value)
    slow.close()

    class BrokenStream:
        def write(self, payload: bytes) -> None:
            raise BrokenPipeError("broken")

        def flush(self) -> None:
            raise BrokenPipeError("broken")

        def close(self) -> None:
            return None

    class BrokenProc:
        stdin = BrokenStream()
        stdout = None

        def poll(self) -> int:
            return 0

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    broken = ExternalMCPClient(_fake_config())
    broken._proc = BrokenProc()  # type: ignore[assignment]
    with pytest.raises(ExternalMCPError) as write_notification:
        broken._send_notification("notifications/test")
    assert "write failed" in str(write_notification.value)
    with pytest.raises(ExternalMCPError) as write_request:
        broken._raw_request("ping")
    assert "write failed" in str(write_request.value)
    broken.close()


def test_mcp_hub_build_failure_and_audit_view(monkeypatch):
    def broken_config(config: Any = None) -> ExternalServerConfig:
        return ExternalServerConfig(
            name="mcp_hub",
            command=("definitely-not-a-real-mcp-binary",),
            env=safe_child_env(),
        )

    monkeypatch.setattr(hub_module, "mcp_hub_server_config", broken_config)
    with pytest.raises(ExternalMCPError):
        hub_module.build_mcp_hub_client()

    event = AuditEvent(
        server="mcp_hub",
        tool="search_servers",
        ok=True,
        duration_ms=3,
        chars=12,
        error_code=None,
    )
    assert audit_dict(event) == {
        "server": "mcp_hub",
        "tool": "search_servers",
        "ok": True,
        "duration_ms": 3,
        "chars": 12,
        "error_code": None,
    }
    with pytest.raises(ValueError):
        MCPHubConfig("hub.sqlite3", pythonpath="")


def test_defensive_branches_via_injected_transport(monkeypatch):
    client = ExternalMCPClient(_fake_config())
    with pytest.raises(ExternalMCPError) as missing:
        client._raw_request("ping", {"a": "b"})
    assert "not available" in str(missing.value)

    class ReadyStream:
        def write(self, payload: bytes) -> None:
            return None

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class ReadyProc:
        stdin = ReadyStream()
        stdout = None

        def poll(self) -> int:
            return 0

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    fatal = ExternalMCPClient(_fake_config())
    fatal._proc = ReadyProc()  # type: ignore[assignment]
    fatal._fatal = ExternalMCPError("transport failed")
    with pytest.raises(ExternalMCPError) as published:
        fatal._raw_request("ping")
    assert "transport failed" in str(published.value)

    values = iter((0.0, 1.0))
    monkeypatch.setattr(external_module.time, "monotonic", lambda: next(values))
    timeout = ExternalMCPClient(_fake_config())
    timeout._proc = ReadyProc()  # type: ignore[assignment]
    with pytest.raises(ExternalMCPError) as expired:
        timeout._raw_request("ping")
    assert "timeout" in str(expired.value)

    empty = ExternalMCPClient(_fake_config())
    monkeypatch.setattr(empty, "start", lambda: None)
    monkeypatch.setattr(empty, "_raw_request", lambda *args, **kwargs: None)
    with pytest.raises(ExternalMCPError) as no_result:
        empty._initialize()
    assert "initialize returned no result object" in str(no_result.value)

    unqualified_config = ExternalServerConfig(
        name="unit",
        command=(sys.executable, "-c", _FAKE_SERVER),
        env=safe_child_env(),
        tool_namespace="",
    )
    unqualified = ExternalMCPClient(unqualified_config)
    assert unqualified._unqualify("echo") == "echo"
    unqualified.close()
    assert client._unqualify("unit.") == "unit."

    shaped = ExternalMCPClient(_fake_config(max_tools=1, allowed_tools=None))
    shaped._initialized = True
    monkeypatch.setattr(shaped, "_raw_request", lambda *args, **kwargs: {})
    with pytest.raises(ExternalMCPError) as no_tools:
        shaped.list_tools()
    assert "no tool list" in str(no_tools.value)

    monkeypatch.setattr(
        shaped,
        "_raw_request",
        lambda *args, **kwargs: {
            "tools": [
                "bad",
                {"name": ""},
                {"name": "first"},
                {"name": "second"},
            ]
        },
    )
    assert shaped.list_tools() == [{"name": "first"}]

    with pytest.raises(ExternalMCPError) as bad_result:
        shaped._result_text("echo", [])
    assert "tool result is not an object" in str(bad_result.value)
    shaped.close()
