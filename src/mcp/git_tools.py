"""Read-only git inspection tools (stdlib + the ``git`` binary).

These are deliberately *read-only*: every command is a reporting command
(``status``/``log``/``diff``/``branch``/``show``). Nothing here can mutate a
repository, which is why they are safe to expose over MCP and to hand to an
agent. Outputs are the raw text git prints, so they compose with any client.

All commands run with ``cwd`` pinned to the workspace root and a hard timeout,
and any ``path`` argument is confined inside that root.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = [
    "GitError",
    "git_branches",
    "git_diff",
    "git_log",
    "git_show",
    "git_status",
    "git_available",
]

#: Hard cap on how long any single git invocation may run.
_TIMEOUT = 15.0


class GitError(RuntimeError):
    """A git command failed, or git is not installed."""


def git_available() -> bool:
    """Whether a ``git`` executable is on PATH."""
    from shutil import which

    return which("git") is not None


def _run(root: Path, args: list[str], timeout: float = _TIMEOUT) -> str:
    """Run ``git <args>`` in ``root`` and return stdout (raise ``GitError`` otherwise)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout:g}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GitError(detail or f"git {' '.join(args)} failed ({proc.returncode})")
    return proc.stdout


def _safe_path(root: Path, raw: object) -> str | None:
    """Confine an optional ``path`` argument inside ``root``; return a relative str."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise GitError("'path' must be a string")
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise GitError(f"path {raw!r} escapes the workspace root {root}")
    return str(resolved.relative_to(root)) if resolved != root else "."


def _limit(raw: object, default: int = 10, maximum: int = 200) -> int:
    """Clamp an optional ``limit`` argument into ``1..maximum``."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return max(1, min(maximum, raw))


def git_status(root: Path) -> str:
    """``git status --short --branch`` — the working-tree summary."""
    return _run(root, ["status", "--short", "--branch"])


def git_log(root: Path, *, limit: object = 10) -> str:
    """``git log --oneline`` for the most recent ``limit`` commits."""
    count = _limit(limit)
    return _run(root, ["log", "--oneline", f"-n{count}"])


def git_branches(root: Path) -> str:
    """Local branches with their tip SHA and upstream."""
    fmt = "%(refname:short)\t%(objectname:short)\t%(upstream:short)"
    return _run(root, ["branch", "--list", f"--format={fmt}"])


def git_diff(
    root: Path,
    *,
    ref: object = None,
    staged: object = False,
    path: object = None,
) -> str:
    """``git diff`` (optionally ``--staged``, a ``ref``, and/or a confined ``path``)."""
    args = ["diff"]
    if isinstance(staged, bool) and staged:
        args.append("--staged")
    if isinstance(ref, str) and ref:
        args.append(ref)
    target = _safe_path(root, path)
    if target is not None:
        args.extend(["--", target])
    return _run(root, args)


def git_show(root: Path, ref: str, *, stat_only: object = False) -> str:
    """``git show`` for ``ref`` (optionally ``--stat`` only)."""
    if not isinstance(ref, str) or not ref.strip():
        raise GitError("a non-empty 'ref' is required")
    args = ["show"]
    if isinstance(stat_only, bool) and stat_only:
        args.append("--stat")
    args.append(ref)
    return _run(root, args)
