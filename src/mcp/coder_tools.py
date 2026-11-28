"""Dev-bounded coder tools exposed through the framework MCP server.

These tools are **opt-in**. ``build_framework_server`` keeps
``include_dev_tools=False`` by default, and mutating calls additionally require
``NEXUS_ENABLE_DEV_TOOLS=1`` plus an explicit per-call ``approval`` decision.
Every call emits exactly one content-free audit event, in the same spirit as
:mod:`src.mcp.external`.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from src.agent_loop.tools import (
    _SENSITIVE_DIRS,
    approval_granted,
    dev_tools_enabled,
    is_sensitive_file,
)
from src.coder.plan import plan_from_json, validate
from src.coder.sandbox import MAX_OUTPUT_BYTES, MAX_TIMEOUT_S
from src.mcp.protocol import error_content, text_content

logger = logging.getLogger(__name__)

CONTAINER_ENV = "NEXUS_ENABLE_CONTAINER_SANDBOX"
MAX_FILES = 32
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_TARGETS = 32
MAX_COMMAND_PARTS = 64
ALLOWED_CHECKS = frozenset({"pytest", "ruff", "mypy"})
# Coder tools can write, so avoid VCS/dependency/build caches in addition to
# the credential-file names already refused by the shared agent-loop helper.
_BLOCKED_DIR_PARTS = _SENSITIVE_DIRS | frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".tox",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
})
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}$")

CODE_DISABLED = -32010
CODE_APPROVAL = -32011
CODE_WORKSPACE = -32012
CODE_PLAN = -32013
CODE_COMMAND = -32014
CODE_LIMIT = -32015
CODE_CONTAINER = -32016
CODE_RUNTIME = -32017

PERMISSION_MODES = {
    "coder_plan_preview": "read_only",
    "coder_apply_plan": "dev_bounded",
    "coder_run_tests": "dev_bounded",
    "coder_container_run": "container_sandbox",
}


class CoderToolError(Exception):
    """A structured, content-free tool refusal."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CoderAuditEvent:
    """One call: no arguments, outputs, paths, approval tokens or secrets."""

    tool: str
    permission_mode: str
    ok: bool
    duration_ms: int
    chars: int
    error_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "permission_mode": self.permission_mode,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "chars": self.chars,
            "error_code": self.error_code,
        }


@dataclass
class CoderAuditLog:
    """Append-only in-memory audit sink for coder tool calls."""

    events: list[CoderAuditEvent] = field(default_factory=list)

    def record(self, event: CoderAuditEvent) -> None:
        self.events.append(event)
        logger.info(
            "coder_mcp tool=%s mode=%s ok=%s duration_ms=%d chars=%d code=%s",
            event.tool,
            event.permission_mode,
            event.ok,
            event.duration_ms,
            event.chars,
            event.error_code,
        )


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _require_dev() -> None:
    if not dev_tools_enabled():
        raise CoderToolError("development tools are disabled by default", CODE_DISABLED)


def _require_approval(arguments: Mapping[str, Any]) -> None:
    if not approval_granted(arguments.get("approval")):
        raise CoderToolError("explicit approval is required", CODE_APPROVAL)


def _require_workspace(arguments: Mapping[str, Any], workspace: Path) -> Path:
    raw = arguments.get("workspace_root")
    if not isinstance(raw, str) or not raw:
        raise CoderToolError("workspace_root is required", CODE_WORKSPACE)
    candidate = Path(raw).expanduser().resolve()
    if candidate != workspace:
        raise CoderToolError("workspace_root does not match the server root", CODE_WORKSPACE)
    return workspace


def _safe_target(workspace: Path, raw: Any) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise CoderToolError("invalid relative path", CODE_WORKSPACE)
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts or raw.startswith("-"):
        raise CoderToolError("path must stay inside the workspace", CODE_WORKSPACE)
    if any(part in _BLOCKED_DIR_PARTS for part in relative.parts):
        raise CoderToolError("path targets a sensitive directory", CODE_WORKSPACE)
    candidate = workspace / relative
    if candidate.is_symlink():
        raise CoderToolError("symlink targets are refused", CODE_WORKSPACE)
    target = candidate.resolve()
    if target != workspace and not target.is_relative_to(workspace):
        raise CoderToolError("path escapes the workspace", CODE_WORKSPACE)
    try:
        inside_parts = target.relative_to(workspace).parts
    except ValueError as exc:  # pragma: no cover - checked above
        raise CoderToolError("path escapes the workspace", CODE_WORKSPACE) from exc
    if any(part in _BLOCKED_DIR_PARTS for part in inside_parts) or is_sensitive_file(target):
        raise CoderToolError("path targets a sensitive file", CODE_WORKSPACE)
    return target, raw


def _validated_plan(arguments: Mapping[str, Any]) -> Any:
    raw = arguments.get("plan")
    if not isinstance(raw, Mapping):
        raise CoderToolError("plan must be an object", CODE_PLAN)
    plan = plan_from_json(dict(raw))
    problems = validate(plan)
    if problems:
        raise CoderToolError("plan validation failed", CODE_PLAN)
    if not 1 <= len(plan.steps) <= MAX_FILES:
        raise CoderToolError("plan file count exceeds the cap", CODE_LIMIT)
    return plan


def _plan_changes(workspace: Path, plan: Any) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    total = 0
    for step in plan.steps:
        target, relative = _safe_target(workspace, step.file)
        if step.action not in ("create", "edit", "delete"):
            raise CoderToolError("unsupported plan action", CODE_PLAN)
        existing = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        new = existing
        if step.action == "create":
            if target.exists():
                raise CoderToolError("create target already exists", CODE_PLAN)
            new = step.patch_hint
        elif step.action == "edit":
            if not target.is_file():
                raise CoderToolError("edit target is missing", CODE_PLAN)
            if existing.count(step.find) != 1:
                raise CoderToolError("edit block must match exactly once", CODE_PLAN)
            new = existing.replace(step.find, step.patch_hint)
        elif step.action == "delete":
            if not target.is_file():
                raise CoderToolError("delete target is missing", CODE_PLAN)
            new = ""
        size = len(new.encode("utf-8"))
        if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
            raise CoderToolError("plan content exceeds byte caps", CODE_LIMIT)
        total += size
        if target.suffix == ".py" and new:
            try:
                compile(new, relative, "exec")
            except SyntaxError as exc:
                raise CoderToolError("python syntax check failed", CODE_PLAN) from exc
        changes.append(
            {
                "target": target,
                "relative": relative,
                "action": step.action,
                "old": existing,
                "new": new,
            }
        )
    return changes


def _diff(workspace: Path, plan: Any) -> str:
    parts: list[str] = []
    for change in _plan_changes(workspace, plan):
        parts.extend(
            difflib.unified_diff(
                change["old"].splitlines(),
                change["new"].splitlines(),
                fromfile=f"a/{change['relative']}",
                tofile=f"b/{change['relative']}",
                lineterm="",
            )
        )
    diff = "\n".join(parts)
    if len(diff.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise CoderToolError("diff exceeds output cap", CODE_LIMIT)
    return diff


def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".coder-tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _bounded_command(argv: list[str], workspace: Path, timeout: Any) -> dict[str, Any]:
    if not 1 <= timeout <= MAX_TIMEOUT_S:
        raise CoderToolError("timeout exceeds the cap", CODE_LIMIT)
    env = {
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_NO_INDEX": "1",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
    }
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, shell=False
            argv,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise CoderToolError("command could not be started", CODE_RUNTIME) from exc

    buffers = {"out": bytearray(), "err": bytearray()}
    truncated = False

    def drain(pipe: Any, key: str) -> None:
        nonlocal truncated
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                sink = buffers[key]
                if len(sink) + len(chunk) > MAX_OUTPUT_BYTES:
                    truncated = True
                if len(sink) < MAX_OUTPUT_BYTES:
                    sink.extend(chunk[: MAX_OUTPUT_BYTES - len(sink)])
        except (OSError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True),
        threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=int(timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:  # pragma: no cover - platform split
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        proc.wait()
    for thread in threads:
        thread.join(timeout=5)
    if timed_out:
        raise CoderToolError("command timed out", CODE_LIMIT)
    if truncated:
        raise CoderToolError("command output exceeded the cap", CODE_LIMIT)
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": buffers["out"].decode("utf-8", "replace"),
        "stderr": buffers["err"].decode("utf-8", "replace"),
    }


@dataclass
class CoderToolkit:
    """Implementation behind the ``coder.*`` MCP tool schemas."""

    workspace: Path
    audit: CoderAuditLog = field(default_factory=CoderAuditLog)

    def call(self, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Call one tool and emit exactly one content-free audit event."""
        started = time.perf_counter()
        ok = False
        chars = 0
        code: int | None = None
        try:
            handler = {
                "coder_plan_preview": self.plan_preview,
                "coder_apply_plan": self.apply_plan,
                "coder_run_tests": self.run_tests,
                "coder_container_run": self.container_run,
            }.get(tool)
            if handler is None:
                raise CoderToolError("unknown coder tool", CODE_RUNTIME)
            result = handler(arguments)
            payload = _json_text(result)
            chars = len(payload)
            ok = True
            return text_content(payload)
        except CoderToolError as exc:
            code = exc.code
            payload = _json_text({"code": exc.code, "message": str(exc)})
            chars = len(payload)
            return error_content(payload)
        except Exception:
            code = CODE_RUNTIME
            payload = _json_text({"code": code, "message": "coder tool failed"})
            chars = len(payload)
            return error_content(payload)
        finally:
            self.audit.record(
                CoderAuditEvent(
                    tool=tool,
                    permission_mode=PERMISSION_MODES.get(tool, "unknown"),
                    ok=ok,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    chars=chars,
                    error_code=code,
                )
            )

    def plan_preview(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Return a unified diff without touching the workspace."""
        plan = _validated_plan(arguments)
        return {
            "ok": True,
            "mode": "read_only",
            "files": len(plan.steps),
            "diff": _diff(self.workspace, plan),
        }

    def apply_plan(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a bounded, pre-validated plan inside the workspace root."""
        _require_dev()
        _require_approval(arguments)
        _require_workspace(arguments, self.workspace)
        changes = _plan_changes(self.workspace, _validated_plan(arguments))
        snapshots: list[tuple[Path, bytes | None]] = []
        try:
            for change in changes:
                target = change["target"]
                snapshots.append((target, target.read_bytes() if target.exists() else None))
                if change["action"] == "delete":
                    target.unlink(missing_ok=True)
                else:
                    _atomic_write(target, change["new"])
        except Exception as exc:
            for target, original in reversed(snapshots):
                try:
                    if original is None:
                        target.unlink(missing_ok=True)
                    else:
                        _atomic_write(target, original.decode("utf-8", "replace"))
                except OSError:
                    pass
            raise CoderToolError(
                "plan application failed; workspace restored", CODE_RUNTIME
            ) from exc
        return {
            "ok": True,
            "mode": "dev_bounded",
            "applied": [change["relative"] for change in changes],
        }

    def run_tests(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Run one allowlisted local check on explicit workspace targets."""
        _require_dev()
        _require_approval(arguments)
        _require_workspace(arguments, self.workspace)
        command = arguments.get("command")
        if not isinstance(command, str) or command not in ALLOWED_CHECKS:
            raise CoderToolError("command is not allowlisted", CODE_COMMAND)
        targets = arguments.get("targets")
        if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
            raise CoderToolError("targets must be a bounded list", CODE_COMMAND)
        checked: list[str] = []
        for raw in targets:
            target, relative = _safe_target(self.workspace, raw)
            if not target.exists():
                raise CoderToolError("check target is missing", CODE_COMMAND)
            checked.append(relative)
        prefix = {
            "pytest": [sys.executable, "-m", "pytest", "-q", "--no-header"],
            "ruff": [sys.executable, "-m", "ruff", "check"],
            "mypy": [sys.executable, "-m", "mypy"],
        }[command]
        argv = [*prefix, *checked]
        if len(argv) > MAX_COMMAND_PARTS:
            raise CoderToolError("command exceeds argument cap", CODE_LIMIT)
        timeout = arguments.get("timeout", MAX_TIMEOUT_S)
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise CoderToolError("timeout must be an integer", CODE_LIMIT)
        outcome = _bounded_command(argv, self.workspace, timeout)
        return {
            "ok": outcome["ok"],
            "mode": "dev_bounded",
            "command": command,
            "exit_code": outcome["exit_code"],
            "stdout": outcome["stdout"],
            "stderr": outcome["stderr"],
        }

    def container_run(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Run a pinned container image with dev tools + explicit approval."""
        _require_dev()
        if os.environ.get(CONTAINER_ENV) != "1":
            raise CoderToolError("container sandbox is disabled", CODE_CONTAINER)
        _require_approval(arguments)
        workspace = _require_workspace(arguments, self.workspace)
        image = arguments.get("image")
        command = arguments.get("command")
        if not isinstance(image, str) or _IMAGE_RE.fullmatch(image) is None:
            raise CoderToolError("image must be pinned by sha256 digest", CODE_CONTAINER)
        if (
            not isinstance(command, list)
            or not command
            or len(command) > MAX_COMMAND_PARTS
            or any(not isinstance(part, str) or not part for part in command)
        ):
            raise CoderToolError("command must be a bounded argv list", CODE_COMMAND)
        try:
            from src.coder.container_sandbox import ContainerSandboxError, run_in_container

            outcome = run_in_container(
                list(command),
                workspace,
                image=image,
                enabled=True,
                approved=True,
                timeout=MAX_TIMEOUT_S,
            )
        except (ContainerSandboxError, OSError, ValueError) as exc:
            raise CoderToolError("container execution refused", CODE_CONTAINER) from exc
        return {
            "ok": bool(outcome.get("ok")),
            "mode": "container_sandbox",
            "exit_code": outcome.get("exit_code"),
        }


def build_coder_toolkit(workspace: str | Path, audit: CoderAuditLog | None = None) -> CoderToolkit:
    """Build a toolkit confined to ``workspace`` with an optional shared audit log."""
    return CoderToolkit(
        workspace=Path(workspace).resolve(),
        audit=audit if audit is not None else CoderAuditLog(),
    )
