"""Filesystem confinement helpers for source files passed to model-backed review."""

from __future__ import annotations

from pathlib import Path


def is_safe_regular_file(root: Path, candidate: Path) -> bool:
    """Accept only ordinary files whose resolved path remains inside root.

    Symlinks are rejected even when they currently point inside the workspace:
    avoiding link traversal keeps review collection predictable and prevents a
    link to a private file outside the selected project from entering model
    context.
    """
    try:
        root_resolved = Path(root).resolve(strict=True)
        candidate_path = Path(candidate)
        if candidate_path.is_symlink():
            return False
        resolved = candidate_path.resolve(strict=True)
        resolved.relative_to(root_resolved)
        return resolved.is_file() and not candidate_path.is_symlink()
    except (OSError, RuntimeError, ValueError):
        return False


__all__ = ["is_safe_regular_file"]
