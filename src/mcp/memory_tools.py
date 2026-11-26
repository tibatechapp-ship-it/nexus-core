"""Bounded project memory and task-plan tracking for Zyko over MCP.

These tools sit on top of the existing :mod:`src.memory` stores. They are
**opt-in** — :func:`~src.mcp.framework.build_framework_server` does not register
them unless ``include_memory_tools=True`` — and writes additionally require
``NEXUS_ENABLE_MEMORY_WRITES=1`` plus an explicit per-call ``approval`` decision.

Every call emits exactly one content-free audit event: tool, permission mode,
ok, duration, output length and a stable error code. Arguments, stored values,
scope identifiers, approval tokens and secrets are never audited or echoed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent_loop.tools import _SENSITIVE_DIRS, approval_granted, is_sensitive_file
from src.coder.sandbox import SEED_SECRET_NAMES
from src.mcp.protocol import error_content, text_content
from src.memory.base import Clock, utc_iso
from src.memory.manager import MemoryManager
from src.memory.semantic import _lexical_score

logger = logging.getLogger("src.mcp.memory_tools")

MEMORY_WRITES_ENV = "NEXUS_ENABLE_MEMORY_WRITES"
DEFAULT_DB_PATH = ".zyko/memory.db"
SOURCE = "mcp.memory_record"

MEMORY_READ_TOOLS: frozenset[str] = frozenset({"memory_recall", "task_plan_get"})
MEMORY_WRITE_TOOLS: frozenset[str] = frozenset({"memory_record", "task_plan_update"})
MEMORY_TOOL_NAMES: frozenset[str] = MEMORY_READ_TOOLS | MEMORY_WRITE_TOOLS

PLAN_STATUSES: tuple[str, str, str] = ("done", "doing", "todo")

MAX_SCOPE_CHARS = 128
MAX_KEY_CHARS = 128
MAX_CONTENT_CHARS = 4096
MAX_QUERY_CHARS = 512
MAX_RECALL_RESULTS = 8
MAX_RECALL_CANDIDATES = 64
MAX_VALUE_CHARS = 512
MAX_PLAN_STEPS = 32
MAX_STEP_ID_CHARS = 64
MAX_STEP_TEXT_CHARS = 256
MAX_PLAN_BYTES = 8 * 1024
MAX_ARGUMENT_COUNT = 32
MAX_ARGUMENT_SERIALIZED_CHARS = 32_000
MAX_DB_PATH_CHARS = 512
MAX_VERSION = 2**31 - 1

CODE_DISABLED = -32020
CODE_APPROVAL = -32021
CODE_SCOPE = -32022
CODE_WORKSPACE = -32023
CODE_SECRET = -32024
CODE_LIMIT = -32025
CODE_CONFLICT = -32026
CODE_RUNTIME = -32027
CODE_INPUT = -32602

PERMISSION_MODES: dict[str, str] = {
    "memory_recall": "read_only",
    "memory_record": "bounded_write",
    "task_plan_get": "read_only",
    "task_plan_update": "bounded_write",
}

_ID_RE = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")
_STEP_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_FORBIDDEN_DIRS = frozenset(_SENSITIVE_DIRS) | frozenset(
    {".git", ".venv", "venv", "node_modules", "secrets", "credentials"}
)
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"),
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|authorization|cookie)\b\s*[:=]\s*\S{6,}"
)

_PLANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_plans (
    project     TEXT NOT NULL,
    session     TEXT NOT NULL,
    version     INTEGER NOT NULL,
    updated_ts  REAL NOT NULL,
    updated_iso TEXT NOT NULL,
    plan_json   TEXT NOT NULL,
    PRIMARY KEY (project, session)
)
"""


class MemoryToolError(Exception):
    """A structured, content-free refusal with a stable code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MemoryAuditEvent:
    """One tool call: no arguments, outputs, scope ids or secrets."""

    tool: str
    permission_mode: str
    ok: bool
    duration_ms: int
    chars: int
    error_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe record with a fixed, content-free key set."""
        return {
            "tool": self.tool,
            "permission_mode": self.permission_mode,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "chars": self.chars,
            "error_code": self.error_code,
        }


@dataclass
class MemoryAuditLog:
    """Append-only in-memory sink, one event per call."""

    events: list[MemoryAuditEvent] = field(default_factory=list)

    def record(self, event: MemoryAuditEvent) -> None:
        """Append one event and emit a content-free log line."""
        self.events.append(event)
        logger.info(
            "zuko_memory tool=%s mode=%s ok=%s duration_ms=%d chars=%d code=%s",
            event.tool,
            event.permission_mode,
            event.ok,
            event.duration_ms,
            event.chars,
            event.error_code,
        )


def memory_tool_schemas() -> dict[str, dict[str, Any]]:
    """Input schemas for the four bounded memory/plan tools."""
    scope = {
        "project": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9._:@-]{1,128}$",
            "description": "ASCII project scope identifier",
        },
        "session": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9._:@-]{1,128}$",
            "description": "ASCII session scope identifier",
        },
    }
    approval = {
        "type": "string",
        "description": "Explicit per-call approval decision for a bounded write",
    }
    return {
        "memory_recall": {
            "type": "object",
            "description": "[read-only] Recall scoped semantic facts; values are redacted and bounded.",
            "properties": {
                **scope,
                "query": {"type": "string", "maxLength": MAX_QUERY_CHARS},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RECALL_RESULTS},
            },
            "required": ["project", "session", "query"],
        },
        "memory_record": {
            "type": "object",
            "description": "[bounded write] Store one secret-free semantic fact in scope.",
            "properties": {
                **scope,
                "key": {"type": "string", "maxLength": MAX_KEY_CHARS},
                "content": {"type": "string", "maxLength": MAX_CONTENT_CHARS},
                "approval": approval,
            },
            "required": ["project", "session", "key", "content", "approval"],
        },
        "task_plan_get": {
            "type": "object",
            "description": "[read-only] Read the scoped plan: done / doing / todo steps.",
            "properties": scope,
            "required": ["project", "session"],
        },
        "task_plan_update": {
            "type": "object",
            "description": "[bounded write] Replace the scoped plan atomically and version it.",
            "properties": {
                **scope,
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_PLAN_STEPS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "maxLength": MAX_STEP_ID_CHARS},
                            "text": {"type": "string", "maxLength": MAX_STEP_TEXT_CHARS},
                            "status": {"type": "string", "enum": list(PLAN_STATUSES)},
                        },
                        "required": ["id", "text", "status"],
                    },
                },
                "expected_version": {"type": "integer", "minimum": 0},
                "approval": approval,
            },
            "required": ["project", "session", "steps", "approval"],
        },
    }


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _find_secret(text: str) -> bool:
    """True when text contains a token/key/credential-shaped sequence."""
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS) or bool(
        _SECRET_ASSIGNMENT.search(text)
    )


def _redact(text: str) -> str:
    """Replace secret-shaped spans without echoing the matched value."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return _SECRET_ASSIGNMENT.sub("[redacted]", text)


def _arguments_size(arguments: Mapping[str, Any]) -> int:
    """Bound argument count and serialized size before any handling."""
    if len(arguments) > MAX_ARGUMENT_COUNT:
        raise MemoryToolError("too many arguments", CODE_LIMIT)
    size = len(json.dumps(arguments, ensure_ascii=False, separators=(",", ":")))
    if size > MAX_ARGUMENT_SERIALIZED_CHARS:
        raise MemoryToolError("arguments exceed the size cap", CODE_LIMIT)
    return size


def _scope(arguments: Mapping[str, Any]) -> tuple[str, str]:
    project = arguments.get("project")
    session = arguments.get("session")
    for value in (project, session):
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise MemoryToolError("invalid project/session scope", CODE_SCOPE)
    return str(project), str(session)


def _subject(scope: tuple[str, str]) -> str:
    return f"{scope[0]}/{scope[1]}"


def _validated_text(raw: Any, *, cap: int, message: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise MemoryToolError(f"{message} must be a non-empty string", CODE_INPUT)
    if len(raw) > cap:
        raise MemoryToolError(f"{message} exceeds the size cap", CODE_LIMIT)
    if any(ord(char) < 32 and char not in "\t\n" for char in raw):
        raise MemoryToolError(f"{message} contains control characters", CODE_INPUT)
    if _find_secret(raw):
        raise MemoryToolError("secret-like content is refused", CODE_SECRET)
    return raw.strip()


def _writes_enabled() -> bool:
    return os.environ.get(MEMORY_WRITES_ENV) == "1"


def _require_write(arguments: Mapping[str, Any]) -> None:
    if not _writes_enabled():
        raise MemoryToolError("memory writes are disabled", CODE_DISABLED)
    if not approval_granted(arguments.get("approval")):
        raise MemoryToolError("explicit approval is required", CODE_APPROVAL)


def _safe_db_path(workspace: Path, raw: Any) -> Path:
    """Resolve the memory DB path inside the workspace, refusing traps."""
    if not isinstance(raw, str) or not raw or "\x00" in raw or len(raw) > MAX_DB_PATH_CHARS:
        raise MemoryToolError("invalid memory database path", CODE_WORKSPACE)
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise MemoryToolError("memory database must stay in the workspace", CODE_WORKSPACE)
    absolute = workspace / candidate
    current = workspace
    for part in absolute.relative_to(workspace).parts:
        current = current / part
        if current.is_symlink():
            raise MemoryToolError("symlink path is refused", CODE_WORKSPACE)
    target = absolute.resolve()
    relative_parts = target.relative_to(workspace).parts
    if any(part in _FORBIDDEN_DIRS for part in relative_parts):
        raise MemoryToolError("sensitive directory is refused", CODE_WORKSPACE)
    lowered = target.name.lower()
    if (
        lowered in SEED_SECRET_NAMES
        or lowered.endswith(_SECRET_SUFFIXES)
        or is_sensitive_file(target)
    ):
        raise MemoryToolError("sensitive database name is refused", CODE_WORKSPACE)
    return target


def _validated_steps(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PLAN_STEPS:
        raise MemoryToolError("plan step count is outside the limit", CODE_LIMIT)
    steps: list[dict[str, str]] = []
    seen: set[str] = set()
    doing = 0
    for item in raw:
        if not isinstance(item, Mapping):
            raise MemoryToolError("invalid plan step", CODE_INPUT)
        step_id = item.get("id")
        if not isinstance(step_id, str) or not _STEP_ID_RE.fullmatch(step_id) or step_id in seen:
            raise MemoryToolError("plan step id is invalid or duplicated", CODE_INPUT)
        seen.add(step_id)
        text = _validated_text(item.get("text"), cap=MAX_STEP_TEXT_CHARS, message="plan step text")
        status = item.get("status")
        if status not in PLAN_STATUSES:
            raise MemoryToolError("unsupported plan status", CODE_INPUT)
        if status == "doing":
            doing += 1
            if doing > 1:
                raise MemoryToolError("only one step may be doing", CODE_INPUT)
        steps.append({"id": step_id, "text": text, "status": str(status)})
    return steps


def _summary(steps: list[dict[str, str]]) -> dict[str, int]:
    return {
        "done": sum(step["status"] == "done" for step in steps),
        "doing": sum(step["status"] == "doing" for step in steps),
        "todo": sum(step["status"] == "todo" for step in steps),
    }


class TaskPlanStore:
    """One bounded plan per ``(project, session)`` in the memory database."""

    def __init__(self, connection: sqlite3.Connection, *, clock: Clock = time.time) -> None:
        self.connection = connection
        self.clock = clock
        self.lock = threading.RLock()
        with self.lock:
            self.connection.execute(_PLANS_SCHEMA)
            self.connection.commit()

    def get(self, scope: tuple[str, str]) -> dict[str, Any]:
        """Return the stored plan or the empty default (version zero)."""
        with self.lock:
            row = self.connection.execute(
                "SELECT version, plan_json FROM task_plans WHERE project = ? AND session = ?",
                scope,
            ).fetchone()
        if row is None:
            return {"version": 0, "steps": [], "summary": {"done": 0, "doing": 0, "todo": 0}}
        steps = list(json.loads(str(row["plan_json"]))["steps"])
        return {"version": int(row["version"]), "steps": steps, "summary": _summary(steps)}

    def update(
        self,
        scope: tuple[str, str],
        steps: list[dict[str, str]],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Atomically replace the plan, optionally gated on its current version."""
        with self.lock:
            row = self.connection.execute(
                "SELECT version FROM task_plans WHERE project = ? AND session = ?", scope
            ).fetchone()
            current = int(row["version"]) if row is not None else 0
            if expected_version is not None and expected_version != current:
                raise MemoryToolError("plan version conflict", CODE_CONFLICT)
            plan_json = _json_text({"steps": steps})
            if len(plan_json.encode("utf-8")) > MAX_PLAN_BYTES:
                raise MemoryToolError("plan exceeds the size cap", CODE_LIMIT)
            version = current + 1
            if version > MAX_VERSION:
                raise MemoryToolError("plan version limit reached", CODE_LIMIT)
            timestamp = self.clock()
            self.connection.execute(
                """
                INSERT INTO task_plans
                    (project, session, version, updated_ts, updated_iso, plan_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, session) DO UPDATE SET
                    version = excluded.version,
                    updated_ts = excluded.updated_ts,
                    updated_iso = excluded.updated_iso,
                    plan_json = excluded.plan_json
                """,
                (*scope, version, timestamp, utc_iso(timestamp), plan_json),
            )
            self.connection.commit()
        return {"version": version, "summary": _summary(steps)}


@dataclass
class MemoryToolkit:
    """Single audited entry point behind the four memory/plan tool schemas."""

    workspace: Path
    manager: MemoryManager
    audit: MemoryAuditLog = field(default_factory=MemoryAuditLog)
    plans: TaskPlanStore | None = None
    on_audit: Callable[[MemoryAuditEvent], None] | None = None

    def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Call one tool and emit exactly one content-free audit event."""
        started = time.perf_counter()
        payload = dict(arguments or {})
        ok = False
        chars = 0
        code: int | None = None
        try:
            _arguments_size(payload)
            handler = {
                "memory_recall": self.memory_recall,
                "memory_record": self.memory_record,
                "task_plan_get": self.task_plan_get,
                "task_plan_update": self.task_plan_update,
            }.get(tool)
            if handler is None:
                raise MemoryToolError("unknown memory tool", CODE_INPUT)
            result = handler(payload)
            payload_text = _json_text(result)
            chars = len(payload_text)
            ok = True
            return text_content(payload_text)
        except MemoryToolError as exc:
            code = exc.code
            payload_text = _json_text({"code": exc.code, "message": str(exc)})
            chars = len(payload_text)
            return error_content(payload_text)
        except Exception:
            code = CODE_RUNTIME
            payload_text = _json_text({"code": code, "message": "memory tool failed"})
            chars = len(payload_text)
            return error_content(payload_text)
        finally:
            event = MemoryAuditEvent(
                tool=tool,
                permission_mode=PERMISSION_MODES.get(tool, "unknown"),
                ok=ok,
                duration_ms=int((time.perf_counter() - started) * 1000),
                chars=chars,
                error_code=code,
            )
            self.audit.record(event)
            if self.on_audit is not None:
                self.on_audit(event)

    def memory_recall(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Search only this scope's semantic facts, redacted and bounded."""
        scope = _scope(arguments)
        query = _validated_text(arguments.get("query"), cap=MAX_QUERY_CHARS, message="query")
        limit = arguments.get("limit", 5)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RECALL_RESULTS
        ):
            raise MemoryToolError("invalid recall limit", CODE_LIMIT)
        with self.manager._lock:
            rows = self.manager.connection.execute(
                """
                SELECT ts, key, value FROM facts WHERE subject = ?
                ORDER BY ts DESC, id DESC LIMIT ?
                """,
                (_subject(scope), MAX_RECALL_CANDIDATES),
            ).fetchall()
        scored = [(_lexical_score(query, f"{row['key']} {row['value']}"), row) for row in rows]
        ranked = [
            row
            for score, row in sorted(scored, key=lambda pair: pair[0], reverse=True)
            if score > 0.0
        ]
        results = [
            {
                "ts": float(row["ts"]),
                "key": str(row["key"]),
                "text": _redact(str(row["value"]))[:MAX_VALUE_CHARS],
            }
            for row in ranked[:limit]
        ]
        return {"ok": True, "mode": "read_only", "count": len(results), "results": results}

    def memory_record(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Store one bounded, secret-free fact under the exact scope."""
        _require_write(arguments)
        scope = _scope(arguments)
        key = arguments.get("key")
        if not isinstance(key, str) or not _STEP_ID_RE.fullmatch(key):
            raise MemoryToolError("invalid memory key", CODE_INPUT)
        content = _validated_text(
            arguments.get("content"), cap=MAX_CONTENT_CHARS, message="content"
        )
        self.manager.semantic.remember(key, content, subject=_subject(scope), source=SOURCE)
        return {"ok": True, "mode": "bounded_write", "recorded": 1}

    def task_plan_get(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Read the scoped plan without echoing secrets in step text."""
        scope = _scope(arguments)
        plan = self._plans.get(scope)
        steps = [
            {**step, "text": _redact(step["text"])[:MAX_VALUE_CHARS]} for step in plan["steps"]
        ]
        return {
            "ok": True,
            "mode": "read_only",
            "version": plan["version"],
            "steps": steps,
            "summary": plan["summary"],
        }

    def task_plan_update(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Replace the scoped plan atomically with an optional version guard."""
        _require_write(arguments)
        scope = _scope(arguments)
        steps = _validated_steps(arguments.get("steps"))
        expected = arguments.get("expected_version")
        if expected is not None:
            if (
                isinstance(expected, bool)
                or not isinstance(expected, int)
                or not 0 <= expected <= MAX_VERSION
            ):
                raise MemoryToolError("invalid expected_version", CODE_INPUT)
        result = self._plans.update(scope, steps, expected_version=expected)
        return {"ok": True, "mode": "bounded_write", **result}

    @property
    def _plans(self) -> TaskPlanStore:
        if self.plans is None:  # pragma: no cover - builder always supplies it
            self.plans = TaskPlanStore(self.manager.connection)
        return self.plans


def build_memory_toolkit(
    workspace: Path,
    *,
    manager: MemoryManager | None = None,
    db_path: str | Path | None = None,
    audit: MemoryAuditLog | None = None,
    on_audit: Callable[[MemoryAuditEvent], None] | None = None,
) -> MemoryToolkit:
    """Build the opt-in, default-deny memory toolkit for a framework server."""
    root = Path(workspace).resolve()
    if db_path is not None and not isinstance(db_path, (str, Path)):
        raise MemoryToolError("invalid memory database path", CODE_WORKSPACE)
    raw_path: str | Path = DEFAULT_DB_PATH if db_path is None else db_path
    path = _safe_db_path(root, str(raw_path))
    owner = manager if manager is not None else MemoryManager(path)
    return MemoryToolkit(
        workspace=root,
        manager=owner,
        audit=audit or MemoryAuditLog(),
        plans=TaskPlanStore(owner.connection),
        on_audit=on_audit,
    )
