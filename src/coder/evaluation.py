"""Reproducible repair benchmark runner with fail-closed execution.

Task files describe a starting workspace and exact textual patch operations.
Commands are never executed on the host: a caller must inject an approved
container executor (normally src.coder.container_sandbox.run_in_container).
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable


class EvaluationError(ValueError):
    """Invalid benchmark task or unsafe workspace operation."""


def _safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(
        part in {"", ".", ".."} or part.startswith(".") for part in pure.parts
    ):
        raise EvaluationError(f"unsafe task path: {relative!r}")
    target = root.joinpath(*pure.parts)
    if root.resolve() not in target.resolve().parents:
        raise EvaluationError(f"path escapes workspace: {relative!r}")
    return target


def _apply_task(root: Path, task: dict[str, Any]) -> None:
    files = task.get("files")
    patches = task.get("patches")
    if not isinstance(files, dict) or not isinstance(patches, list):
        raise EvaluationError("task requires files object and patches array")
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise EvaluationError("task files must map paths to text")
        target = _safe_path(root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for patch in patches:
        if not isinstance(patch, dict) or not all(
            isinstance(patch.get(key), str) for key in ("path", "find", "replace")
        ):
            raise EvaluationError("each patch requires path, find and replace strings")
        target = _safe_path(root, patch["path"])
        if not target.is_file() or target.is_symlink():
            raise EvaluationError("patch target must be an existing regular file")
        original = target.read_text(encoding="utf-8")
        needle = patch["find"]
        if not needle or original.count(needle) != 1:
            raise EvaluationError("patch find text must match exactly once")
        target.write_text(original.replace(needle, patch["replace"], 1), encoding="utf-8")


def _digest_expected(root: Path, expected: dict[str, str]) -> tuple[bool, list[str]]:
    mismatches = []
    for name, content in expected.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise EvaluationError("expected_files must map paths to text")
        target = _safe_path(root, name)
        if not target.is_file() or target.is_symlink():
            mismatches.append(name)
            continue
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_hash != expected_hash:
            mismatches.append(name)
    return not mismatches, mismatches


def evaluate_tasks(
    tasks: list[dict[str, Any]],
    *,
    executor: Callable[..., dict[str, Any]] | None = None,
    image: str = "",
    enabled: bool = False,
    approved: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """Evaluate candidate patches; no executor means a deliberate fail-closed result."""
    if not isinstance(tasks, list) or not tasks:
        raise EvaluationError("at least one benchmark task is required")
    if executor is None:
        return {"ok": False, "error": "no approved isolated executor configured",
                "tasks_total": len(tasks), "tasks_passed": 0, "results": []}
    results = []
    started = time.monotonic()
    for task in tasks:
        task_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", task_id):
            raise EvaluationError("task id is missing or invalid")
        command = task.get("test_command")
        if not isinstance(command, list) or not command or any(
            not isinstance(part, str) or not part or len(part) > 4096 for part in command
        ):
            raise EvaluationError(f"{task_id}: test_command must be a non-empty argv list")
        with tempfile.TemporaryDirectory(prefix="nexus-eval-") as directory:
            workspace = Path(directory)
            _apply_task(workspace, task)
            expected_ok, mismatches = _digest_expected(
                workspace, task.get("expected_files", {})
            )
            if not expected_ok:
                results.append({"id": task_id, "ok": False,
                                "reason": "patch_output_mismatch",
                                "mismatched_files": mismatches, "tests": None})
                continue
            execution = executor(
                command, workspace, image=image, enabled=enabled,
                approved=approved, timeout=timeout,
            )
            if not isinstance(execution, dict):
                raise EvaluationError("executor returned a non-object result")
            passed = execution.get("ok") is True
            results.append({
                "id": task_id, "ok": passed,
                "reason": "passed" if passed else "test_execution_failed",
                "tests": {
                    "exit_code": execution.get("exit_code"),
                    "timeout": bool(execution.get("timeout", False)),
                    "stdout": str(execution.get("stdout", ""))[-4000:],
                    "stderr": str(execution.get("stderr", ""))[-4000:],
                },
            })
    total = len(results)
    tasks_passed = sum(1 for item in results if item["ok"])
    duration_ms = round((time.monotonic() - started) * 1000, 2)
    return {
        "ok": tasks_passed == total,
        "tasks_total": total,
        "tasks_passed": tasks_passed,
        "pass_rate": round(tasks_passed / total, 4) if total else 0.0,
        "duration_ms": duration_ms,
        "results": results,
    }


def container_executor(
    command: list[str], workspace: Path, *, image: str, enabled: bool,
    approved: bool, timeout: int = 120,
) -> dict[str, Any]:
    """Lazy adapter to the pinned-image Docker sandbox; Docker errors fail closed."""
    from src.coder.container_sandbox import run_in_container

    return run_in_container(
        command, workspace, image=image, enabled=enabled,
        approved=approved, timeout=timeout,
    )
