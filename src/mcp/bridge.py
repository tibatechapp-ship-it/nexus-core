"""MCP tool execution for framework agents.

:class:`MCPToolExecutor` is a drop-in sibling of
:class:`~src.tools.executor.LocalToolExecutor`: it exposes the same
``execute``/``run`` surface (so it plugs into the exact same ReAct loop) but
resolves ``<tool-call>`` markers against a live MCP server — in-process or over
stdio — instead of local files.

Nothing in the framework has to change to use it::

    from src.mcp import build_framework_server, MCPToolExecutor

    executor = MCPToolExecutor.from_server(build_framework_server(root="."))
    tool_run = executor.run(agent, "list the files and read README.md")
    print(tool_run.result.output, executor.tool_schemas(prefix="mcp_"))
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from src.core.types import AgentResult, Message
from src.mcp.client import InProcessClient, MCPClientError, StdioClient, to_tool_schemas
from src.mcp.server import MCPServer
from src.tools.executor import ToolCall, ToolOutcome, ToolRun, parse_tool_calls
from src.tools.schemas import ToolSchema

__all__ = ["MCPToolExecutor"]

#: Anything that can run an MCP ``tools/list`` + ``tools/call``.
ClientLike = Any


class MCPToolExecutor:
    """Run an agent's tool calls against an MCP server.

    ``client`` only needs ``list_tools()`` and ``call_tool(name, arguments)`` —
    both :class:`~src.mcp.client.InProcessClient` and
    :class:`~src.mcp.client.StdioClient` qualify (and so does any test double).
    """

    def __init__(
        self,
        client: ClientLike,
        *,
        max_steps: int = 5,
        max_calls_per_step: int = 5,
        allowed_tools: frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.max_steps = max_steps
        self.max_calls_per_step = max_calls_per_step
        self.allowed_tools = allowed_tools

    @classmethod
    def from_server(cls, server: MCPServer, **kwargs: Any) -> "MCPToolExecutor":
        """Wrap a local :class:`~src.mcp.server.MCPServer` in-process."""
        return cls(InProcessClient(server), **kwargs)

    @classmethod
    def from_stdio(cls, command: list[str] | None = None, **kwargs: Any) -> "MCPToolExecutor":
        """Wrap a server launched as a subprocess over stdio.

        With no ``command`` the framework server is launched
        (``python -m src.mcp``).
        """
        from src.mcp.client import default_server_command

        client = StdioClient(command or default_server_command())
        client.start()
        return cls(client, **kwargs)

    # -- introspection -----------------------------------------------------
    def tool_names(self) -> list[str]:
        """The names the MCP server currently advertises."""
        return [str(tool.get("name", "")) for tool in self.client.list_tools()]

    def tool_schemas(self, *, prefix: str = "") -> list[ToolSchema]:
        """The server's tools as framework :class:`ToolSchema` objects."""
        return to_tool_schemas(self.client.list_tools(), prefix=prefix)

    # -- dispatch ----------------------------------------------------------
    def execute(
        self, call: ToolCall, *, allowed_tools: frozenset[str] | None = None
    ) -> ToolOutcome:
        """Run one tool call over MCP (never raises — failures become outcomes)."""
        permit = self.allowed_tools if allowed_tools is None else allowed_tools
        if permit is not None and call.name not in permit:
            return ToolOutcome(
                name=call.name,
                ok=False,
                error=f"agent is not permitted to use tool {call.name!r}",
            )
        if not isinstance(call.arguments, Mapping):
            arguments: Mapping[str, Any] = {}
        else:
            arguments = call.arguments
        try:
            output = self.client.call_tool(call.name, dict(arguments))
        except MCPClientError as exc:
            return ToolOutcome(name=call.name, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a remote tool must never crash the loop
            return ToolOutcome(name=call.name, ok=False, error=f"{type(exc).__name__}: {exc}")
        return ToolOutcome(name=call.name, ok=True, output=output)

    def run(
        self,
        agent: Any,
        task: str,
        *,
        context: str = "",
        lessons: str = "",
        max_steps: int | None = None,
        max_calls_per_step: int | None = None,
    ) -> ToolRun:
        """Run ``agent`` on ``task`` in a bounded ReAct loop using MCP tools.

        The loop mirrors :meth:`~src.tools.executor.LocalToolExecutor.run`
        exactly — same ``<tool-call>`` protocol, same metrics/state bookkeeping,
        same never-raise contract — only the tool backend differs.
        """
        steps_limit = self.max_steps if max_steps is None else max_steps
        calls_limit = self.max_calls_per_step if max_calls_per_step is None else max_calls_per_step

        agent.state.mark_busy(task)
        started = time.perf_counter()
        messages = agent.build_messages(task, context)
        if lessons:
            messages = agent._with_lessons(messages, lessons)  # same-package contract
        outcomes: list[ToolOutcome] = []
        steps = 0
        output = ""
        try:
            while steps < steps_limit:
                steps += 1
                output = agent.backend.generate(messages, model=agent.model)
                if not isinstance(output, str):
                    raise TypeError(f"backend returned {type(output).__name__!r}, expected str")
                calls = parse_tool_calls(output)
                if not calls:
                    break
                messages.append(Message("assistant", output))
                for call in calls[:calls_limit]:
                    outcome = self.execute(call, allowed_tools=self.allowed_tools)
                    outcomes.append(outcome)
                    messages.append(Message("user", outcome.as_prompt()))
        except Exception as exc:  # noqa: BLE001 - a tool run must never crash callers
            elapsed = time.perf_counter() - started
            agent.metrics.record(elapsed, ok=False)
            agent.state.mark_error(str(exc))
            return ToolRun(
                result=AgentResult(agent=agent.name, ok=False, error=str(exc), duration_s=elapsed),
                outcomes=tuple(outcomes),
                steps=steps,
            )
        elapsed = time.perf_counter() - started
        agent.metrics.record(elapsed, ok=True)
        agent.state.mark_idle()
        return ToolRun(
            result=AgentResult(agent=agent.name, ok=True, output=output, duration_s=elapsed),
            outcomes=tuple(outcomes),
            steps=steps,
        )
