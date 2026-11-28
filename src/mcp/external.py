"""Client for external MCP servers built with the official Python SDK.

`src.mcp.client.StdioClient` speaks this repository's own stateless protocol
(``server/discover``, no handshake).  Official-SDK servers speak standard MCP:
``initialize`` -> ``notifications/initialized`` -> ``tools/list`` /
``tools/call`` over newline-delimited JSON-RPC on stdio (SDK 1.30/2.x).

This module adds that second transport without changing the existing client.
It is deliberately small, standard-library only, and reusable for any external
stdio MCP server: the command, environment, limits and tool allowlist are
configuration, not code.

Security posture: explicit child environment, bounded messages/results, strict
tool allowlist, input-schema validation, untrusted-output neutralisation and
bounded reconnect.  Tool results are data, never instructions.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from src.mcp.client import MCPClientError, content_text, to_tool_schemas
from src.tools.schemas import ToolSchema

__all__ = [
    "AuditEvent",
    "DEFAULT_PROTOCOL_VERSION",
    "ExternalMCPClient",
    "ExternalMCPError",
    "ExternalMCPTransportError",
    "ExternalServerConfig",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "safe_child_env",
    "sanitize_audit_tool",
    "sanitize_tool_output",
]

logger = logging.getLogger("src.mcp.external")

#: SDK 1.30 (mcp-hub >=1.27,<3) negotiates 2025-11-25 and echoes it back.
DEFAULT_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_MAX_OUTPUT_CHARS = 12_000
DEFAULT_TIMEOUT_S = 5.0
MAX_RESOURCE_URI_CHARS = 512

_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})
ArgumentBounds = Mapping[str, int | float]
ArgumentLimits = Mapping[str, Mapping[str, ArgumentBounds]]
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
#: Variables intentionally inherited by an external MCP child process.  Nothing
#: else from the parent environment (API keys, tokens, proxy secrets) is passed.
PASSTHROUGH_ENV: tuple[str, ...] = ("PATH", "LANG", "LC_ALL", "PYTHONIOENCODING")
#: Sequences an untrusted tool result could use to masquerade as framework traffic.
_INJECTION_RE = re.compile(
    r"</?(?:tool-call|tool-result|system|instructions|assistant|user)\b|<\|\w+[^>]*\|>",
    re.IGNORECASE,
)
#: Audits record the tool name only. Keep it a short ASCII token so an untrusted
#: or rejected name cannot smuggle arguments, secrets or log-forging text into it.
_AUDIT_TOOL_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")


class ExternalMCPError(MCPClientError):
    """A transport, handshake, policy or tool-result failure (not a crash)."""


class ExternalMCPTransportError(ExternalMCPError):
    """A retryable transport failure (as opposed to a tool/policy error)."""


@dataclass(frozen=True, slots=True)
class ExternalServerConfig:
    """Everything needed to launch and constrain one external MCP server."""

    name: str
    command: tuple[str, ...]
    cwd: str | Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    protocol_version: str = DEFAULT_PROTOCOL_VERSION
    supported_versions: tuple[str, ...] = SUPPORTED_PROTOCOL_VERSIONS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    max_tools: int = 100
    max_reconnects: int = 1
    reconnect_window_s: float = 60.0
    #: Bounded retries after a transport failure. Only tools explicitly marked
    #: safe in ``retry_safe_tools`` are ever replayed; default is no replay.
    max_call_retries: int = 0
    retry_safe_tools: frozenset[str] = frozenset()
    #: Adapter-side numeric bounds. Official SDK tool schemas can drop
    #: ``minimum``/``maximum``, so policy supplies them explicitly.
    argument_limits: ArgumentLimits = field(default_factory=dict)
    allowed_tools: frozenset[str] | None = None
    #: Exact resource URIs permitted for ``resources/read``. ``None`` means no
    #: resource reads; default-deny is deliberate and discovery cannot widen it.
    allowed_resources: frozenset[str] | None = None
    #: When set (e.g. ``"mcp_hub"``), only ``<namespace>.<tool>`` is stripped
    #: before dispatch; a generic adapter with no namespace accepts bare names.
    tool_namespace: str = ""

    def __post_init__(self) -> None:
        """Reject unusable or unsafe configuration before any process is spawned."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.name):
            raise ValueError("server name must be a short ASCII identifier")
        if not self.command or any(not isinstance(part, str) or not part for part in self.command):
            raise ValueError("command must be a non-empty sequence of strings")
        if self.protocol_version not in self.supported_versions:
            raise ValueError("requested protocol version is not in supported_versions")
        if self.timeout_s <= 0 or self.max_response_bytes < 512 or self.max_output_chars < 64:
            raise ValueError("timeout and size limits must be positive and meaningful")
        if self.max_tools < 1 or self.max_reconnects < 0 or self.reconnect_window_s <= 0:
            raise ValueError("tool/reconnect limits must be positive")
        if self.max_call_retries < 0 or self.max_call_retries > 2:
            raise ValueError("max_call_retries must be between 0 and 2")
        if not all(isinstance(name, str) and name for name in self.retry_safe_tools):
            raise ValueError("retry_safe_tools must contain non-empty strings")
        for tool, params in self.argument_limits.items():
            if not isinstance(tool, str) or not tool or not isinstance(params, Mapping):
                raise ValueError("argument_limits must map tool names to parameter maps")
            for param, bounds in params.items():
                if not isinstance(param, str) or not param or not isinstance(bounds, Mapping):
                    raise ValueError("argument_limits bounds must be parameter mappings")
                for key in ("minimum", "maximum"):
                    if key in bounds and (
                        not isinstance(bounds[key], (int, float)) or isinstance(bounds[key], bool)
                    ):
                        raise ValueError(f"argument_limits {key} must be numeric")
        if self.tool_namespace and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.tool_namespace):
            raise ValueError("tool_namespace must be a short ASCII identifier")
        if self.allowed_tools is not None and not all(
            isinstance(name, str) and sanitize_audit_tool(name) == name
            for name in self.allowed_tools
        ):
            raise ValueError("allowed_tools must contain short ASCII tool names")
        if self.allowed_resources is not None and not all(
            isinstance(uri, str)
            and uri
            and len(uri) <= MAX_RESOURCE_URI_CHARS
            and "\x00" not in uri
            for uri in self.allowed_resources
        ):
            raise ValueError("allowed_resources must contain short, non-empty URIs")
        for key, value in self.env.items():
            if not _ENV_KEY_RE.fullmatch(key):
                raise ValueError(f"unsafe environment variable name: {key!r}")
            if not isinstance(value, str) or "\n" in value or "\r" in value or len(value) > 4096:
                raise ValueError(f"invalid value for environment variable {key!r}")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One tool call, without arguments, output or any secret-bearing field."""

    server: str
    tool: str
    ok: bool
    duration_ms: int
    chars: int
    error_code: int | None = None

    def __post_init__(self) -> None:
        """A rejected or untrusted tool name never reaches the audit record."""
        object.__setattr__(self, "tool", sanitize_audit_tool(self.tool))

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe audit record."""
        return {
            "server": self.server,
            "tool": self.tool,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "chars": self.chars,
            "error_code": self.error_code,
        }


def safe_child_env(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a minimal child environment from a fixed allowlist plus overrides."""
    env: dict[str, str] = {}
    for key in PASSTHROUGH_ENV:
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key, value in (overrides or {}).items():
        if not _ENV_KEY_RE.fullmatch(key):
            raise ValueError(f"unsafe environment variable name: {key!r}")
        if not isinstance(value, str) or "\n" in value or "\r" in value or len(value) > 4096:
            raise ValueError(f"invalid value for environment variable {key!r}")
        env[key] = value
    return env


def sanitize_tool_output(text: str) -> str:
    """Neutralise framework-marker injection in untrusted MCP result text."""
    return _INJECTION_RE.sub(lambda match: match.group(0).replace("<", "&lt;"), text)


def sanitize_audit_tool(name: str) -> str:
    """Return a safe audit token; anything untrusted becomes ``<invalid>``."""
    if not isinstance(name, str) or not _AUDIT_TOOL_RE.fullmatch(name):
        return "<invalid>"
    return name


def _matches_type(value: Any, expected: str) -> bool:
    """True when ``value`` matches a JSON-schema primitive type."""
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "object":
        return isinstance(value, Mapping)
    return True


def _validate_arguments(
    spec: Mapping[str, Any],
    arguments: Mapping[str, Any],
    limits: Mapping[str, ArgumentBounds] | None = None,
) -> str | None:
    """Validate call arguments against schema plus adapter-side numeric bounds."""
    schema = spec.get("inputSchema")
    schema = schema if isinstance(schema, Mapping) else {}
    properties = schema.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    for name in required_names:
        if name not in arguments:
            return f"missing required parameter {name!r}"
    for name, value in arguments.items():
        if properties and name not in properties:
            return f"unknown parameter {name!r}"
        prop = properties.get(name)
        prop = prop if isinstance(prop, Mapping) else {}
        expected = prop.get("type")
        if (
            isinstance(expected, str)
            and expected in _JSON_TYPES
            and not _matches_type(value, expected)
        ):
            return f"parameter {name!r} must be {expected}"
        if _matches_type(value, "number"):
            minimum = prop.get("minimum")
            if (
                isinstance(minimum, (int, float))
                and not isinstance(minimum, bool)
                and value < minimum
            ):
                return f"parameter {name!r} must be >= {minimum}"
            maximum = prop.get("maximum")
            if (
                isinstance(maximum, (int, float))
                and not isinstance(maximum, bool)
                and value > maximum
            ):
                return f"parameter {name!r} must be <= {maximum}"
        bounds = limits.get(name, {}) if limits is not None else {}
        if bounds and _matches_type(value, "number"):
            minimum = bounds.get("minimum")
            if (
                isinstance(minimum, (int, float))
                and not isinstance(minimum, bool)
                and value < minimum
            ):
                return f"parameter {name!r} must be >= {minimum}"
            maximum = bounds.get("maximum")
            if (
                isinstance(maximum, (int, float))
                and not isinstance(maximum, bool)
                and value > maximum
            ):
                return f"parameter {name!r} must be <= {maximum}"
        enum = prop.get("enum")
        if isinstance(enum, list) and value not in enum:
            return f"parameter {name!r} must be one of {enum!r}"
        if isinstance(value, str) and len(value) > 16_384:
            return f"parameter {name!r} is too long"
    return None


class ExternalMCPClient:
    """A bounded, reconnectable client for an official-SDK MCP subprocess."""

    def __init__(
        self,
        config: ExternalServerConfig,
        *,
        on_audit: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.config = config
        self.on_audit = on_audit
        self._proc: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._queue: queue.Queue[Any] = queue.Queue()
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._fatal: ExternalMCPError | None = None
        self._closing = False
        self._stopping = False
        self._initialized = False
        self._schemas: dict[str, dict[str, Any]] = {}
        self._server_info: dict[str, Any] = {}
        self._negotiated_version: str | None = None
        self._reconnect_times: list[float] = []

    # -- lifecycle ---------------------------------------------------------
    @property
    def running(self) -> bool:
        """Whether the external process is currently alive."""
        return self._proc is not None and self._proc.poll() is None

    @property
    def server_info(self) -> Mapping[str, Any]:
        """The identity returned by the ``initialize`` handshake."""
        return dict(self._server_info)

    @property
    def protocol_version(self) -> str | None:
        """The protocol version the server negotiated."""
        return self._negotiated_version

    def _permitted_tool_names(self) -> frozenset[str]:
        """Configured allowlist, or the discovered schemas when none was set.

        ``None`` never means "any name": dispatch is still constrained to tools
        the server actually advertised and validated by ``tools/list``.
        """
        if self.config.allowed_tools is not None:
            return self.config.allowed_tools
        return frozenset(self._schemas)

    def _validated_tool_name(self, name: str) -> str:
        """Unqualify and reject unsafe names before they reach a subprocess."""
        candidate = self._unqualify(name)
        if sanitize_audit_tool(candidate) != candidate:
            raise ExternalMCPError("tool name must be a short ASCII identifier", code=-32602)
        return candidate

    def start(self) -> None:
        """Spawn the child and start its reader thread (idempotent)."""
        if self._closing:
            raise ExternalMCPError("client is closed", code=-32000)
        if self.running:
            return
        if self._fatal is not None:
            raise self._fatal
        try:
            proc = subprocess.Popen(  # noqa: S603 - caller-supplied, explicitly configured command
                list(self.config.command),
                cwd=str(self.config.cwd) if self.config.cwd is not None else None,
                env=dict(self.config.env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise ExternalMCPError(f"cannot start external MCP server: {exc}") from exc
        self._proc = proc
        assert proc.stdout is not None
        self._reader_thread = threading.Thread(
            target=self._reader,
            args=(proc.stdout,),
            name=f"external-mcp-{self.config.name}",
            daemon=True,
        )
        self._reader_thread.start()

    def close(self) -> None:
        """Terminate the child, join the reader and drop all session state."""
        self._closing = True
        self._stop_process()

    def __enter__(self) -> ExternalMCPClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _stop_process(self) -> None:
        """Stop the child without permanently closing the client."""
        self._stopping = True
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
                    proc.kill()
                    proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    stream.close()
        thread, self._reader_thread = self._reader_thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._queue = queue.Queue()
        self._fatal = None
        self._initialized = False
        self._negotiated_version = None
        self._server_info = {}
        self._schemas = {}
        self._stopping = False

    # -- wire transport ----------------------------------------------------
    def _set_fatal(self, error: ExternalMCPTransportError) -> None:
        """Publish a fatal transport error to every waiter exactly once."""
        if self._closing or self._stopping or self._fatal is not None:
            return
        self._fatal = error
        self._queue.put(error)

    def _reader(self, stream: BinaryIO) -> None:
        """Parse framed JSON-RPC messages from stdout into the shared queue."""
        try:
            while True:
                raw = stream.readline()
                if not raw:
                    break
                if len(raw) > self.config.max_response_bytes:
                    self._set_fatal(
                        ExternalMCPTransportError("response exceeds configured byte limit")
                    )
                    return
                if not raw.strip():
                    continue
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._set_fatal(ExternalMCPTransportError("invalid JSON from external server"))
                    return
                if not isinstance(message, dict):
                    self._set_fatal(
                        ExternalMCPTransportError("external server response is not an object")
                    )
                    return
                self._queue.put(message)
        except (OSError, ValueError):
            self._set_fatal(ExternalMCPTransportError("stdio read failed"))
        finally:
            self._set_fatal(ExternalMCPTransportError("external server closed the connection"))

    def _send_notification(self, method: str) -> None:
        """Write a JSON-RPC notification (no id, no response expected)."""
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ExternalMCPError("server process is not available", code=-32000)
        payload = json.dumps({"jsonrpc": "2.0", "method": method}, separators=(",", ":")).encode()
        with self._write_lock:
            try:
                proc.stdin.write(payload + b"\n")
                proc.stdin.flush()
            except OSError as exc:
                self._set_fatal(ExternalMCPTransportError(f"write failed: {type(exc).__name__}"))
                raise self._fatal or ExternalMCPTransportError("write failed") from exc

    def _raw_request(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Send one request and wait for its matching response within the timeout."""
        self._next_id += 1
        request_id = self._next_id
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params or {}),
            },
            separators=(",", ":"),
        ).encode()
        if len(payload) > self.config.max_response_bytes:
            raise ExternalMCPError("request exceeds configured byte limit", code=-32602)
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ExternalMCPError("server process is not available", code=-32000)
        with self._write_lock:
            try:
                proc.stdin.write(payload + b"\n")
                proc.stdin.flush()
            except OSError as exc:
                self._set_fatal(ExternalMCPTransportError(f"write failed: {type(exc).__name__}"))
                raise self._fatal or ExternalMCPTransportError("write failed") from exc
        deadline = time.monotonic() + self.config.timeout_s
        while True:
            if self._fatal is not None:
                raise self._fatal
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExternalMCPTransportError(
                    f"timeout after {self.config.timeout_s}s: {method}", code=-32000
                )
            try:
                message = self._queue.get(timeout=remaining)
            except queue.Empty as exc:
                raise ExternalMCPTransportError(
                    f"timeout after {self.config.timeout_s}s: {method}", code=-32000
                ) from exc
            if isinstance(message, ExternalMCPError):
                raise message
            if not isinstance(message, Mapping) or message.get("id") != request_id:
                continue  # notification or another waiter's response
            error = message.get("error")
            if isinstance(error, Mapping):
                raise ExternalMCPError(
                    str(error.get("message", "external MCP error")),
                    code=error.get("code") if isinstance(error.get("code"), int) else None,
                    data=error.get("data"),
                )
            return message.get("result")

    # -- handshake / discovery / calls ------------------------------------
    def _initialize(self) -> None:
        """Perform the official MCP handshake and verify the negotiated version."""
        self.start()
        result = self._raw_request(
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "nexus-core", "version": "1.71.0"},
            },
        )
        if not isinstance(result, Mapping):
            raise ExternalMCPError("initialize returned no result object", code=-32603)
        version = result.get("protocolVersion")
        if version not in self.config.supported_versions:
            raise ExternalMCPError(f"unsupported protocol version: {version!r}", code=-32022)
        info = result.get("serverInfo")
        self._server_info = dict(info) if isinstance(info, Mapping) else {}
        self._negotiated_version = str(version)
        self._send_notification("notifications/initialized")
        self._initialized = True

    def _ensure_ready(self) -> None:
        """Reconnect within budget if needed, then complete the handshake."""
        if self._closing:
            raise ExternalMCPError("client is closed", code=-32000)
        if self._proc is not None and self._proc.poll() is not None:
            self._set_fatal(ExternalMCPTransportError("external server closed the connection"))
        if self._fatal is not None:
            self._reconnect()
        if not self._initialized:
            self._initialize()

    def _reconnect(self) -> None:
        """Restart once per bounded window, re-handshake and re-discover tools.

        A failed call is NEVER replayed: restarting a read-only server is safe,
        duplicating an in-flight call is not.  The caller may retry explicitly.
        """
        now = time.monotonic()
        window = self.config.reconnect_window_s
        self._reconnect_times = [stamp for stamp in self._reconnect_times if now - stamp <= window]
        if len(self._reconnect_times) >= self.config.max_reconnects:
            raise ExternalMCPError("reconnect budget exhausted", code=-32000)
        self._reconnect_times.append(now)
        self._stop_process()
        self._initialize()
        self.list_tools()

    def _unqualify(self, name: str) -> str:
        """Strip only this server's namespace, never an arbitrary prefix."""
        if not isinstance(name, str) or not name:
            raise ExternalMCPError("tool name must be a non-empty string", code=-32602)
        namespace = self.config.tool_namespace
        if not namespace:
            return name
        prefix = f"{namespace}."
        if name.startswith(prefix):
            tail = name[len(prefix) :]
            if tail:
                return tail
        return name

    def list_tools(self) -> list[dict[str, Any]]:
        """Discover tools after the handshake, filtered by the configured allowlist."""
        self._ensure_ready()
        result = self._raw_request("tools/list", {})
        tools = result.get("tools") if isinstance(result, Mapping) else None
        if not isinstance(tools, list):
            raise ExternalMCPError("tools/list returned no tool list", code=-32603)
        selected: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, Mapping):
                continue
            name = tool.get("name")
            if not isinstance(name, str) or sanitize_audit_tool(name) != name:
                continue
            if self.config.allowed_tools is not None and name not in self.config.allowed_tools:
                continue
            selected.append(dict(tool))
            if len(selected) >= self.config.max_tools:
                break
        self._schemas = {str(tool["name"]): tool for tool in selected}
        return selected

    def tool_names(self) -> list[str]:
        """Advertised, permitted tool names."""
        return [str(tool.get("name", "")) for tool in self.list_tools()]

    def tool_schemas(self, *, prefix: str = "") -> list[ToolSchema]:
        """Convert discovered tools into framework ``ToolSchema`` objects."""
        return to_tool_schemas(self.list_tools(), prefix=prefix)

    def _result_text(self, name: str, result: Any) -> str:
        """Validate, bound and neutralise a ``tools/call`` result."""
        if not isinstance(result, Mapping):
            raise ExternalMCPError("tool result is not an object", code=-32603)
        blocks = result.get("content")
        if not isinstance(blocks, list):
            raise ExternalMCPError("tool result has no content blocks", code=-32603)
        text = content_text(result)
        if len(text) > self.config.max_output_chars:
            text = text[: self.config.max_output_chars] + (
                f"\n[truncated at {self.config.max_output_chars} chars]"
            )
        if result.get("isError") is True:
            raise ExternalMCPError(
                f"{self.config.name} tool {name} failed: {text[:300]}", code=-32000
            )
        return sanitize_tool_output(text)

    def _resource_text(self, result: Any) -> str:
        """Validate, bound and neutralise a ``resources/read`` result."""
        if not isinstance(result, Mapping):
            raise ExternalMCPError("resource result is not an object", code=-32603)
        contents = result.get("contents")
        if not isinstance(contents, list) or not contents:
            raise ExternalMCPError("resource result has no contents", code=-32603)
        blocks: list[str] = []
        for block in contents:
            if not isinstance(block, Mapping) or not isinstance(block.get("text"), str):
                raise ExternalMCPError("resource content block has no text", code=-32603)
            blocks.append(block["text"])
        if result.get("isError") is True:
            raise ExternalMCPError("resource read failed", code=-32000)
        text = "\n".join(blocks)
        if len(text) > self.config.max_output_chars:
            text = text[: self.config.max_output_chars] + (
                f"\n[truncated at {self.config.max_output_chars} chars]"
            )
        return sanitize_tool_output(text)

    def read_resource(self, uri: str) -> str:
        """Read one exact-allowlisted resource with a single content-free audit."""
        started = time.perf_counter()
        chars = 0
        code: int | None = None
        failed = False
        try:
            if (
                not isinstance(uri, str)
                or not uri
                or len(uri) > MAX_RESOURCE_URI_CHARS
                or "\x00" in uri
            ):
                raise ExternalMCPError(
                    "resource URI must be a short, non-empty string", code=-32602
                )
            allowed = self.config.allowed_resources
            if allowed is None or uri not in allowed:
                raise ExternalMCPError(
                    f"resource is not allowed by {self.config.name} policy", code=-32001
                )
            self._ensure_ready()
            result = self._raw_request("resources/read", {"uri": uri})
            text = self._resource_text(result)
            chars = len(text)
            return text
        except Exception as exc:
            failed = True
            code = exc.code if isinstance(exc, MCPClientError) else None
            raise
        finally:
            self._audit(
                AuditEvent(
                    server=self.config.name,
                    tool="resources/read",
                    ok=not failed,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    chars=chars,
                    error_code=code,
                )
            )

    def _audit(self, event: AuditEvent) -> None:
        """Log an audit record without arguments or result content."""
        logger.info(
            "external_mcp server=%s tool=%s ok=%s duration_ms=%d chars=%d code=%s",
            event.server,
            event.tool,
            event.ok,
            event.duration_ms,
            event.chars,
            event.error_code,
        )
        if self.on_audit is not None:
            self.on_audit(event)

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> str:
        """Call one permitted, advertised tool and return sanitised text.

        A transport failure may be replayed once for tools explicitly listed in
        ``retry_safe_tools`` (mcp-hub marks all of its read-only catalog tools).
        Policy, schema and tool errors are never replayed.  One audit event is
        emitted for the logical call, regardless of internal retries.
        """
        tool_name = ""
        args = dict(arguments or {})
        started = time.perf_counter()
        chars = 0
        code: int | None = None
        failed = False
        try:
            tool_name = self._validated_tool_name(name)
            allowed = self.config.allowed_tools
            if allowed is not None and tool_name not in allowed:
                # Denied tools must never spawn the child process.
                raise ExternalMCPError(
                    f"tool {tool_name!r} is not allowed by {self.config.name} policy", code=-32001
                )
            self._ensure_ready()
            if not self._schemas:
                self.list_tools()
            if tool_name not in self._permitted_tool_names():
                # With no configured allowlist, the advertised schemas are the
                # allowlist — discovery can never widen it by itself.
                raise ExternalMCPError(
                    f"tool {tool_name!r} is not declared by {self.config.name}", code=-32601
                )
            spec = self._schemas.get(tool_name)
            if spec is None:
                raise ExternalMCPError(
                    f"tool {tool_name!r} is not advertised by {self.config.name}", code=-32601
                )
            limits = self.config.argument_limits.get(tool_name, {})
            problem = _validate_arguments(spec, args, limits)
            if problem is not None:
                raise ExternalMCPError(problem, code=-32602)
            attempt = 0
            while True:
                try:
                    result = self._raw_request("tools/call", {"name": tool_name, "arguments": args})
                    text = self._result_text(tool_name, result)
                    chars = len(text)
                    return text
                except ExternalMCPTransportError:
                    retryable = (
                        attempt < self.config.max_call_retries
                        and tool_name in self.config.retry_safe_tools
                        and not self._closing
                    )
                    if not retryable:
                        raise
                    attempt += 1
                    self._reconnect()
        except Exception as exc:
            failed = True
            code = exc.code if isinstance(exc, MCPClientError) else None
            raise
        finally:
            self._audit(
                AuditEvent(
                    server=self.config.name,
                    tool=tool_name or "<invalid>",
                    ok=not failed,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    chars=chars,
                    error_code=code,
                )
            )
