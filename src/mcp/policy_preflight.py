"""Read-only policy preflight for nexus-core tools and resources.

``dry_run_policy`` answers one bounded question before a tool is really called:
would the current policy accept this step?  It is deliberately structural — it
never starts a subprocess, performs a file write, runs a command or reads a
secret.  The decision and its audit event contain stable reason codes only, so
arguments, URIs, paths and outputs cannot leak into logs.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.coder.sandbox import MAX_FILE_BYTES, SEED_SECRET_NAMES
from src.mcp.external import _matches_type

__all__ = [
    "CODE_ALLOWED",
    "CODE_DENIED",
    "CODE_INTERNAL",
    "CODE_INVALID",
    "CODE_LIMIT",
    "KIND_PATH",
    "KIND_PLAN",
    "KIND_RESOURCE_READ",
    "KIND_TOOL_CALL",
    "MODE_READ_ONLY",
    "PreflightAuditEvent",
    "PreflightAuditLog",
    "PreflightDecision",
    "PreflightRefusal",
    "PreflightToolkit",
    "build_preflight_toolkit",
    "preflight_tool_schema",
]

logger = logging.getLogger("src.mcp.policy_preflight")

KIND_TOOL_CALL = "tool_call"
KIND_RESOURCE_READ = "resource_read"
KIND_PATH = "path"
KIND_PLAN = "plan"
_VALID_KINDS = frozenset({KIND_TOOL_CALL, KIND_RESOURCE_READ, KIND_PATH, KIND_PLAN})

MODE_READ_ONLY = "read_only"
TOOL_NAME = "dry_run_policy"

CODE_ALLOWED = 0
CODE_DENIED = -32001
CODE_INVALID = -32602
CODE_LIMIT = -32003
CODE_INTERNAL = -32000

MAX_URI_CHARS = 512
MAX_ARGUMENT_CHARS = 16_384
MAX_ARGUMENT_SERIALIZED_CHARS = 64_000
MAX_ARGUMENT_COUNT = 128
MAX_PLAN_STEPS = 32
MAX_PLAN_BYTES = MAX_FILE_BYTES

_SENSITIVE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "coverage",
        "secrets",
    }
)
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})
_ACTION_ALLOWLIST = frozenset({"create", "edit", "delete"})


class PreflightRefusal(Exception):
    """A content-free, structured refusal with a stable code."""

    def __init__(self, reason: str, code: int = CODE_INVALID) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    """A read-only decision: stable reason and code, no checked values."""

    ok: bool
    reason: str
    code: int
    kind: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe decision returned to the caller."""
        return {"ok": self.ok, "reason": self.reason, "code": self.code, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class PreflightAuditEvent:
    """One preflight call, without arguments, values, paths or secrets."""

    tool: str
    mode: str
    ok: bool
    duration_ms: int
    chars: int
    error_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe audit record."""
        return {
            "tool": self.tool,
            "mode": self.mode,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "chars": self.chars,
            "error_code": self.error_code,
        }


@dataclass
class PreflightAuditLog:
    """Append-only in-memory sink for preflight decisions."""

    events: list[PreflightAuditEvent] = field(default_factory=list)

    def record(self, event: PreflightAuditEvent) -> None:
        """Append one event and emit a content-free log line."""
        self.events.append(event)
        logger.info(
            "policy_preflight tool=%s mode=%s ok=%s duration_ms=%d chars=%d code=%s",
            event.tool,
            event.mode,
            event.ok,
            event.duration_ms,
            event.chars,
            event.error_code,
        )


def preflight_tool_schema() -> dict[str, Any]:
    """Input schema for the single default-deny preflight tool."""
    return {
        "type": "object",
        "description": "Structurally check a tool/resource/path/plan without side effects.",
        "properties": {
            "kind": {"type": "string", "enum": sorted(_VALID_KINDS)},
            "tool": {"type": "string", "description": "Tool name for tool_call checks."},
            "arguments": {"type": "object", "description": "Arguments for tool_call checks."},
            "tool_schema": {"type": "object", "description": "Declared JSON schema for the tool."},
            "uri": {"type": "string", "description": "Resource URI for resource_read checks."},
            "path": {"type": "string", "description": "Relative path for path checks."},
            "plan": {"type": "object", "description": "Deterministic plan object."},
        },
        "required": ["kind"],
    }


def _safe_path(workspace: Path, raw: Any) -> Path:
    """Resolve a relative path without touching files or leaving the workspace."""
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PreflightRefusal("invalid_path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts or raw.startswith("-"):
        raise PreflightRefusal("path_outside_workspace", CODE_DENIED)
    if any(part in _SENSITIVE_DIRS for part in relative.parts):
        raise PreflightRefusal("sensitive_path", CODE_DENIED)
    candidate = workspace / relative
    if candidate.is_symlink():
        raise PreflightRefusal("symlink_path", CODE_DENIED)
    target = candidate.resolve()
    if target != workspace and not target.is_relative_to(workspace):
        raise PreflightRefusal("path_outside_workspace", CODE_DENIED)
    inside_parts = target.relative_to(workspace).parts
    if any(part in _SENSITIVE_DIRS for part in inside_parts):
        raise PreflightRefusal("sensitive_path", CODE_DENIED)
    lowered = target.name.lower()
    if (
        lowered in SEED_SECRET_NAMES
        or lowered.startswith(".env")
        or lowered.endswith(_SECRET_SUFFIXES)
    ):
        raise PreflightRefusal("sensitive_path", CODE_DENIED)
    return target


def _arguments_size(arguments: Mapping[str, Any]) -> int:
    """Bounded size estimate; oversized values are refused, never serialised."""
    if len(arguments) > MAX_ARGUMENT_COUNT:
        raise PreflightRefusal("arguments_too_large", CODE_LIMIT)
    text = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_ARGUMENT_SERIALIZED_CHARS:
        raise PreflightRefusal("arguments_too_large", CODE_LIMIT)
    return len(text)


def _check_schema(
    spec: Mapping[str, Any],
    arguments: Mapping[str, Any],
    limits: Mapping[str, Mapping[str, int | float]],
) -> None:
    """Validate a tool call against a declared schema plus adapter limits."""
    schema = spec.get("inputSchema")
    schema = schema if isinstance(schema, Mapping) else {}
    properties = schema.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    for name in required_names:
        if name not in arguments:
            raise PreflightRefusal("missing_required_parameter")
    for name, value in arguments.items():
        if properties and name not in properties:
            raise PreflightRefusal("unknown_parameter")
        prop = properties.get(name)
        prop = prop if isinstance(prop, Mapping) else {}
        expected = prop.get("type")
        if (
            isinstance(expected, str)
            and expected in _JSON_TYPES
            and not _matches_type(value, expected)
        ):
            raise PreflightRefusal("parameter_type_mismatch")
        bounds: dict[str, int | float] = {}
        for source in (prop, limits.get(name, {})):
            for key in ("minimum", "maximum"):
                bound = source.get(key)
                if isinstance(bound, (int, float)) and not isinstance(bound, bool):
                    bounds[key] = bound
        if _matches_type(value, "number"):
            minimum = bounds.get("minimum")
            maximum = bounds.get("maximum")
            if minimum is not None and value < minimum:
                raise PreflightRefusal("parameter_below_minimum", CODE_LIMIT)
            if maximum is not None and value > maximum:
                raise PreflightRefusal("parameter_above_maximum", CODE_LIMIT)
        enum = prop.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise PreflightRefusal("parameter_enum_mismatch")
        if isinstance(value, str) and len(value) > MAX_ARGUMENT_CHARS:
            raise PreflightRefusal("parameter_too_long", CODE_LIMIT)


class PreflightToolkit:
    """One entry point that checks policies without executing anything."""

    def __init__(
        self,
        workspace: Path,
        *,
        audit: PreflightAuditLog | None = None,
        allowed_tools: frozenset[str] = frozenset(),
        allowed_resources: frozenset[str] = frozenset(),
        tool_specs: Mapping[str, Mapping[str, Any]] | None = None,
        argument_limits: Mapping[str, Mapping[str, Mapping[str, int | float]]] | None = None,
        max_plan_steps: int = MAX_PLAN_STEPS,
        on_audit: Callable[[PreflightAuditEvent], None] | None = None,
    ) -> None:
        """Store policy inputs; no files, processes or commands are touched."""
        self.workspace = Path(workspace).resolve()
        self.audit = audit or PreflightAuditLog()
        self.on_audit = on_audit
        self.allowed_tools = frozenset(allowed_tools)
        self.allowed_resources = frozenset(allowed_resources)
        self.tool_specs = dict(tool_specs or {})
        self.argument_limits = dict(argument_limits or {})
        if max_plan_steps < 1 or max_plan_steps > MAX_PLAN_STEPS:
            raise ValueError(f"max_plan_steps must be 1..{MAX_PLAN_STEPS}")
        self.max_plan_steps = max_plan_steps
        if not all(isinstance(name, str) and name for name in self.allowed_tools):
            raise ValueError("allowed_tools must contain non-empty strings")
        if not all(isinstance(uri, str) and uri for uri in self.allowed_resources):
            raise ValueError("allowed_resources must contain non-empty URIs")

    # -- public entry point -------------------------------------------------
    def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return one audited, read-only decision for ``dry_run_policy``."""
        started = time.perf_counter()
        kind = "<invalid>"
        payload = dict(arguments or {})
        raw_kind = payload.get("kind")
        if isinstance(raw_kind, str) and raw_kind in _VALID_KINDS:
            kind = raw_kind
        try:
            if tool != TOOL_NAME:
                raise PreflightRefusal("unknown_preflight_tool")
            decision = self._decide(payload)
            kind = decision.kind
        except PreflightRefusal as exc:
            decision = PreflightDecision(False, exc.reason, exc.code, kind)
        except Exception:  # noqa: BLE001 - never leak internals through preflight
            decision = PreflightDecision(False, "internal_error", CODE_INTERNAL, kind)
        event = PreflightAuditEvent(
            tool=TOOL_NAME,
            mode=MODE_READ_ONLY,
            ok=decision.ok,
            duration_ms=int((time.perf_counter() - started) * 1000),
            chars=len(json.dumps(decision.to_dict(), separators=(",", ":"))),
            error_code=None if decision.ok else decision.code,
        )
        self.audit.record(event)
        if self.on_audit is not None:
            self.on_audit(event)
        return decision.to_dict()

    # -- checks -------------------------------------------------------------
    def _decide(self, arguments: Mapping[str, Any]) -> PreflightDecision:
        kind = arguments.get("kind")
        if not isinstance(kind, str) or kind not in _VALID_KINDS:
            raise PreflightRefusal("unknown_check_kind")
        if kind == KIND_TOOL_CALL:
            self._check_tool_call(arguments)
        elif kind == KIND_RESOURCE_READ:
            self._check_resource(arguments)
        elif kind == KIND_PATH:
            _safe_path(self.workspace, arguments.get("path"))
        else:
            self._check_plan(arguments.get("plan"))
        return PreflightDecision(True, "allowed", CODE_ALLOWED, kind)

    def _check_tool_call(self, arguments: Mapping[str, Any]) -> None:
        name = arguments.get("tool")
        if not isinstance(name, str) or not name or len(name) > 128:
            raise PreflightRefusal("invalid_tool_name")
        if name not in self.allowed_tools:
            raise PreflightRefusal("tool_not_allowed", CODE_DENIED)
        call_arguments = arguments.get("arguments")
        if not isinstance(call_arguments, Mapping):
            raise PreflightRefusal("invalid_arguments")
        _arguments_size(call_arguments)
        spec = self.tool_specs.get(name, {})
        if not isinstance(spec, Mapping):
            raise PreflightRefusal("invalid_tool_schema")
        limits = self.argument_limits.get(name, {})
        if not isinstance(limits, Mapping):
            raise PreflightRefusal("invalid_argument_limits")
        _check_schema(spec, call_arguments, limits)

    def _check_resource(self, arguments: Mapping[str, Any]) -> None:
        uri = arguments.get("uri")
        if not isinstance(uri, str) or not uri or len(uri) > MAX_URI_CHARS:
            raise PreflightRefusal("invalid_resource_uri")
        if uri not in self.allowed_resources:
            raise PreflightRefusal("resource_not_allowed", CODE_DENIED)

    def _check_plan(self, plan: Any) -> None:
        if not isinstance(plan, Mapping):
            raise PreflightRefusal("invalid_plan")
        steps = plan.get("steps")
        if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= self.max_plan_steps:
            raise PreflightRefusal("plan_step_count", CODE_LIMIT)
        total = 0
        for step in steps:
            if not isinstance(step, Mapping):
                raise PreflightRefusal("invalid_plan_step")
            if step.get("action") not in _ACTION_ALLOWLIST:
                raise PreflightRefusal("unsupported_plan_action", CODE_DENIED)
            _safe_path(self.workspace, step.get("file"))
            for key in ("find", "patch_hint"):
                value = step.get(key, "")
                if not isinstance(value, str):
                    raise PreflightRefusal("invalid_plan_content")
                total += len(value.encode("utf-8"))
                if total > MAX_PLAN_BYTES:
                    raise PreflightRefusal("plan_content_too_large", CODE_LIMIT)


def build_preflight_toolkit(
    workspace: Path,
    *,
    audit: PreflightAuditLog | None = None,
    allowed_tools: frozenset[str] = frozenset(),
    allowed_resources: frozenset[str] = frozenset(),
    tool_specs: Mapping[str, Mapping[str, Any]] | None = None,
    argument_limits: Mapping[str, Mapping[str, Mapping[str, int | float]]] | None = None,
    max_plan_steps: int = MAX_PLAN_STEPS,
    on_audit: Callable[[PreflightAuditEvent], None] | None = None,
) -> PreflightToolkit:
    """Build the default-deny preflight toolkit for a framework server."""
    return PreflightToolkit(
        workspace,
        audit=audit,
        allowed_tools=allowed_tools,
        allowed_resources=allowed_resources,
        tool_specs=tool_specs,
        argument_limits=argument_limits,
        max_plan_steps=max_plan_steps,
        on_audit=on_audit,
    )
