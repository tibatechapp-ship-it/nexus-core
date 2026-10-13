"""Build a nexus-core MCP server over the framework's real surface.

:func:`build_framework_server` exposes, as MCP tools:

* the **20 built-in agents** (``agent_<name>``) — each runs its agent with a task;
* the **8-agent security scanner** — ``security_scan`` (a path) and
  ``security_scan_text`` (a snippet);
* the **read-only local tools** — ``read_file`` / ``list_dir`` / ``grep``,
  confined to a workspace root exactly like :class:`~src.tools.executor.LocalToolExecutor`;
* the **read-only git tools** — ``git_status`` / ``git_log`` / ``git_branches`` /
  ``git_diff`` / ``git_show`` (:mod:`src.mcp.git_tools`).

Heavy framework modules are imported lazily inside the builders, so importing
this module is cheap and side-effect free.

``python -m src.mcp`` runs this server over stdio.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from src.mcp.protocol import error_content, text_content
from src.mcp.server import MCPServer

__all__ = [
    "AGENT_SCHEMA",
    "build_framework_server",
    "serve_framework",
]

#: Input schema shared by every ``agent_*`` tool.
AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "The task for the agent to perform"},
        "context": {"type": "string", "description": "Optional extra context"},
    },
    "required": ["task"],
}

_PROFILE_ENUM = ("full", "secrets", "dependencies", "web", "apk")


def _framework_version() -> str:
    """The framework's declared version, or ``"0.0.0"`` if unavailable."""
    try:
        import src

        return str(src.__version__)
    except Exception:  # pragma: no cover - version is a nicety, never fatal
        return "0.0.0"

def _default_backend() -> Any:
    """An offline echo backend — enough to exercise agents with no API key."""
    from src.core.backend import EchoBackend

    return EchoBackend()


def build_framework_server(
    *,
    backend: Any = None,
    root: str | Path | None = None,
    include_agents: bool = True,
    include_security: bool = True,
    include_local_tools: bool = True,
    include_git: bool = True,
    name: str = "nexus-core",
    version: str | None = None,
) -> MCPServer:
    """Assemble the framework-surface MCP server.

    ``backend`` is used to instantiate the agents (default: an offline
    :class:`~src.core.backend.EchoBackend`); ``root`` confines the read-only tools
    and the security scanner (default: the current directory).
    """
    workspace = Path(root or Path.cwd()).resolve()
    server = MCPServer(
        name=name,
        version=version or _framework_version(),
        instructions=(
            "nexus-core framework tools: 20 specialised agents, a static security "
            "scanner, read-only workspace tools and read-only git inspection."
        ),
    )
    if include_agents:
        _add_agent_tools(server, backend if backend is not None else _default_backend())
    if include_security:
        _add_security_tools(server, workspace)
    if include_local_tools:
        _add_local_tools(server, workspace)
    if include_git:
        _add_git_tools(server, workspace)
    return server


# -- agents ----------------------------------------------------------------
def _add_agent_tools(server: MCPServer, backend: Any) -> None:
    """Register one ``agent_<name>`` tool per built-in agent."""
    from src.agents import all_agents

    for agent in all_agents(backend):
        server.register(
            f"agent_{agent.name}",
            _make_agent_handler(agent),
            description=f"[{agent.group}] {agent.description}",
            input_schema=AGENT_SCHEMA,
        )


def _make_agent_handler(agent: Any) -> Any:
    """A handler that runs ``agent`` and returns its output or its error."""

    def handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
        task = arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            return error_content("a non-empty string 'task' argument is required")
        context = arguments.get("context")
        result = agent.run(task, context=context if isinstance(context, str) else "")
        if not result.ok:
            return error_content(result.error or "agent run failed")
        return text_content(result.output)

    return handler


# -- security --------------------------------------------------------------
def _add_security_tools(server: MCPServer, workspace: Path) -> None:
    """Register the two security-scanner tools."""
    server.register(
        "security_scan",
        _make_scan_path_handler(workspace),
        description="Scan a file or directory under the workspace root for security issues.",
        input_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Path to scan (confined to root)"},
                "profile": {"type": "string", "enum": list(_PROFILE_ENUM), "default": "full"},
            },
            "required": ["target"],
        },
    )
    server.register(
        "security_scan_text",
        _make_scan_text_handler(),
        description="Scan an in-memory code snippet for security issues.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Code/text to scan"},
                "path": {"type": "string", "description": "Virtual filename for context"},
                "profile": {"type": "string", "enum": list(_PROFILE_ENUM), "default": "full"},
            },
            "required": ["text"],
        },
    )


def _confine(workspace: Path, raw: Any) -> Path:
    """Resolve ``raw`` and refuse anything that escapes ``workspace``."""
    if not isinstance(raw, str) or not raw:
        raise ValueError("a non-empty string path is required")
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else workspace / candidate).resolve()
    if resolved != workspace and not resolved.is_relative_to(workspace):
        raise PermissionError(f"path {raw!r} escapes the workspace root {workspace}")
    return resolved


def _scan_profile(arguments: Mapping[str, Any]) -> str:
    """The requested scan profile, defaulting to ``"full"``."""
    from src.security.profiles import PROFILES

    profile = arguments.get("profile")
    if isinstance(profile, str) and profile in PROFILES:
        return profile
    return "full"


def _make_scan_path_handler(workspace: Path) -> Any:
    """Handler for ``security_scan`` (a confined file/tree)."""

    def handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from src.security.orchestrator import SecurityOrchestrator

        try:
            target = _confine(workspace, arguments.get("target"))
        except (ValueError, PermissionError) as exc:
            return error_content(str(exc))
        if not target.exists():
            return error_content(f"scan target does not exist: {target}")
        report = SecurityOrchestrator().scan(target, profile=_scan_profile(arguments))
        return text_content(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    return handler


def _make_scan_text_handler() -> Any:
    """Handler for ``security_scan_text`` (an in-memory snippet)."""

    def handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from src.security.orchestrator import SecurityOrchestrator

        text = arguments.get("text")
        if not isinstance(text, str):
            return error_content("a string 'text' argument is required")
        path = arguments.get("path")
        report = SecurityOrchestrator().scan_text(
            text,
            path=path if isinstance(path, str) and path else "<string>",
            profile=_scan_profile(arguments),
        )
        return text_content(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    return handler


# -- local read-only tools -------------------------------------------------
def _add_local_tools(server: MCPServer, workspace: Path) -> None:
    """Register ``read_file`` / ``list_dir`` / ``grep`` over the workspace."""
    server.register(
        "read_file",
        _make_executor_handler(workspace, "read"),
        description="Read a UTF-8 text file inside the workspace root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    )
    server.register(
        "list_dir",
        _make_executor_handler(workspace, "list"),
        description="List a directory inside the workspace root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path"}},
        },
    )
    server.register(
        "grep",
        _make_executor_handler(workspace, "grep"),
        description="Search files under a path for a regular expression.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression"},
                "path": {"type": "string", "description": "Directory or file to search"},
                "max_matches": {"type": "integer", "description": "Cap on matches"},
            },
            "required": ["pattern"],
        },
    )


def _make_executor_handler(workspace: Path, executor_tool: str) -> Any:
    """A handler delegating to :class:`LocalToolExecutor` for one safe tool."""

    def handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from src.tools.executor import LocalToolExecutor, ToolCall

        executor = LocalToolExecutor(root=workspace)
        outcome = executor.execute(ToolCall(name=executor_tool, arguments=dict(arguments)))
        if outcome.ok:
            return text_content(outcome.output)
        return error_content(outcome.error or "tool failed")

    return handler


# -- read-only git tools ---------------------------------------------------
def _add_git_tools(server: MCPServer, workspace: Path) -> None:
    """Register the read-only git inspection tools."""
    from src.mcp import git_tools as git

    server.register(
        "git_status",
        _make_git_handler(workspace, lambda root, _args: git.git_status(root)),
        description="Working-tree summary (git status --short --branch).",
        input_schema={"type": "object", "properties": {}},
    )
    server.register(
        "git_log",
        _make_git_handler(workspace, lambda root, args: git.git_log(root, limit=args.get("limit", 10))),
        description="Recent commits (git log --oneline).",
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10, "minimum": 1}},
        },
    )
    server.register(
        "git_branches",
        _make_git_handler(workspace, lambda root, _args: git.git_branches(root)),
        description="Local branches with tip SHA and upstream.",
        input_schema={"type": "object", "properties": {}},
    )
    server.register(
        "git_diff",
        _make_git_handler(
            workspace,
            lambda root, args: git.git_diff(
                root,
                ref=args.get("ref"),
                staged=args.get("staged", False),
                path=args.get("path"),
            ),
        ),
        description="Unified diff, optionally --staged, against a ref, or scoped to a path.",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Revision to diff against"},
                "staged": {"type": "boolean", "default": False, "description": "Use --staged"},
                "path": {"type": "string", "description": "Path (confined to root)"},
            },
        },
    )
    server.register(
        "git_show",
        _make_git_handler(workspace, lambda root, args: git.git_show(root, str(args.get("ref", "")))),
        description="Show a commit or object (git show).",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Revision to show"},
                "stat_only": {"type": "boolean", "default": False},
            },
            "required": ["ref"],
        },
    )


def _make_git_handler(workspace: Path, fn: Callable[[Path, Mapping[str, Any]], str]) -> Any:
    """A handler that runs one read-only git function and maps errors to content."""

    def handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
        from src.mcp.git_tools import GitError

        try:
            return text_content(fn(workspace, arguments))
        except GitError as exc:
            return error_content(str(exc))

    return handler


def serve_framework(**kwargs: Any) -> None:
    """Build the framework server and serve it over stdio."""
    build_framework_server(**kwargs).run_stdio()
