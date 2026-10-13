"""Tests for src.mcp.bridge — running framework agents against MCP tools."""

from __future__ import annotations

from src.core.types import Message
from src.mcp import bridge as bridge_mod
from src.mcp.bridge import MCPToolExecutor
from src.mcp.client import MCPClientError
from src.mcp.server import MCPServer
from src.tools.executor import ToolCall


class _FakeClient:
    """Minimal MCP client double: list_tools + call_tool."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self):  # noqa: ANN201
        return [
            {
                "name": "echo",
                "description": "echo a message",
                "inputSchema": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                    "required": ["msg"],
                },
            }
        ]

    def call_tool(self, name, arguments=None):  # noqa: ANN001, ANN202
        self.calls.append((name, dict(arguments or {})))
        if self.fail is not None:
            raise self.fail
        return f"echo:{dict(arguments or {}).get('msg', '')}"


class _ScriptedBackend:
    """A backend that returns a fixed script of outputs, in order."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls = 0

    def generate(self, messages: list[Message], model: str | None = None) -> str:
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return self.outputs[index]


def _echo_server() -> MCPServer:
    server = MCPServer("bridge-test", "1")
    server.register("echo", lambda args: f"echo:{args.get('msg', '')}")
    return server


# ── execute ───────────────────────────────────────────────────────────────
def test_execute_success():
    executor = MCPToolExecutor(_FakeClient())
    outcome = executor.execute(ToolCall(name="echo", arguments={"msg": "hi"}))
    assert outcome.ok is True
    assert outcome.output == "echo:hi"


def test_execute_refuses_disallowed_tool():
    executor = MCPToolExecutor(_FakeClient(), allowed_tools=frozenset({"other"}))
    outcome = executor.execute(ToolCall(name="echo", arguments={}))
    assert outcome.ok is False
    assert "not permitted" in (outcome.error or "")


def test_execute_client_error_becomes_outcome():
    executor = MCPToolExecutor(_FakeClient(fail=MCPClientError("nope")))
    outcome = executor.execute(ToolCall(name="echo", arguments={"msg": "x"}))
    assert outcome.ok is False
    assert outcome.error == "nope"


def test_execute_unexpected_error_becomes_outcome():
    executor = MCPToolExecutor(_FakeClient(fail=RuntimeError("boom")))
    outcome = executor.execute(ToolCall(name="echo", arguments={}))
    assert outcome.ok is False
    assert "RuntimeError" in (outcome.error or "")


def test_execute_non_mapping_arguments():
    client = _FakeClient()
    executor = MCPToolExecutor(client)
    outcome = executor.execute(ToolCall(name="echo", arguments="not-a-mapping"))  # type: ignore[arg-type]
    assert outcome.ok is True
    assert client.calls == [("echo", {})]


# ── introspection ─────────────────────────────────────────────────────────
def test_tool_names_and_schemas():
    executor = MCPToolExecutor(_FakeClient())
    assert executor.tool_names() == ["echo"]
    schemas = executor.tool_schemas(prefix="mcp_")
    assert schemas[0].name == "mcp_echo"
    assert schemas[0].parameters[0].name == "msg"


def test_from_server_wraps_inprocess_client():
    executor = MCPToolExecutor.from_server(_echo_server())
    assert executor.tool_names() == ["echo"]
    assert executor.execute(ToolCall(name="echo", arguments={"msg": "yo"})).output == "echo:yo"


# ── run loop ──────────────────────────────────────────────────────────────
def _analyst(backend):  # noqa: ANN001, ANN202
    from src.agents.analyst import AnalystAgent

    return AnalystAgent(backend)


def test_run_executes_tool_then_finishes():
    from src.tools.executor import ToolRun

    backend = _ScriptedBackend(
        [
            "working <tool-call name=\"echo\" args='{\"msg\": \"hi\"}'/>",
            "all done",
        ]
    )
    agent = _analyst(backend)
    executor = MCPToolExecutor(_FakeClient())
    tool_run: ToolRun = executor.run(agent, "do it")
    assert tool_run.result.ok is True
    assert tool_run.result.output == "all done"
    assert tool_run.steps == 2
    assert len(tool_run.outcomes) == 1
    assert tool_run.outcomes[0].output == "echo:hi"


def test_run_respects_max_steps():
    backend = _ScriptedBackend(["<tool-call name=\"echo\" args='{}'/>"])
    executor = MCPToolExecutor(_FakeClient(), max_steps=2)
    tool_run = executor.run(_analyst(backend), "loop forever")
    assert tool_run.steps == 2
    assert len(tool_run.outcomes) == 2


def test_run_backend_failure_is_captured():
    class _Boom:
        def generate(self, messages, model=None):  # noqa: ANN001, ANN202
            raise RuntimeError("dead backend")

    tool_run = MCPToolExecutor(_FakeClient()).run(_analyst(_Boom()), "x")
    assert tool_run.result.ok is False
    assert "dead backend" in (tool_run.result.error or "")


def test_run_non_string_output_is_captured():
    class _Weird:
        def generate(self, messages, model=None):  # noqa: ANN001, ANN202
            return 123  # not a str

    tool_run = MCPToolExecutor(_FakeClient()).run(_analyst(_Weird()), "x")
    assert tool_run.result.ok is False
    assert "expected str" in (tool_run.result.error or "")


def test_run_honours_allowed_tools():
    backend = _ScriptedBackend(
        ["<tool-call name=\"echo\" args='{\"msg\": \"hi\"}'/>", "done"]
    )
    executor = MCPToolExecutor(_FakeClient(), allowed_tools=frozenset({"other"}))
    tool_run = executor.run(_analyst(backend), "x")
    assert tool_run.outcomes[0].ok is False


def test_run_injects_lessons():
    seen: dict[str, list] = {}

    class _Capturing:
        def generate(self, messages, model=None):  # noqa: ANN001, ANN202
            seen["messages"] = list(messages)
            return "done"

    tool_run = MCPToolExecutor(_FakeClient()).run(
        _analyst(_Capturing()), "x", lessons="always be terse"
    )
    assert tool_run.result.ok is True
    assert any("always be terse" in m.content for m in seen["messages"])


# ── from_stdio ────────────────────────────────────────────────────────────
def test_from_stdio_launches_default_command(monkeypatch):
    recorded: dict[str, object] = {}

    class _FakeStdio:
        def __init__(self, command):  # noqa: ANN001
            recorded["command"] = command

        def start(self) -> None:
            recorded["started"] = True

        def list_tools(self):  # noqa: ANN201
            return [{"name": "echo", "description": "", "inputSchema": {}}]

        def call_tool(self, name, arguments=None):  # noqa: ANN001, ANN202
            return "ok"

    monkeypatch.setattr(bridge_mod, "StdioClient", _FakeStdio)
    executor = MCPToolExecutor.from_stdio()
    assert recorded["started"] is True
    assert executor.tool_names() == ["echo"]
