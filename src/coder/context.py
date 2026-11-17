"""Evidence-grounded source context for the coding engine.

The planner must inspect relevant source, not just a repository-size summary.
This module builds a deterministic, bounded context from defect locations and
their direct Python import neighbours. It is read-only and never executes code.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_FILES = 8
MAX_FILE_BYTES = 8 * 1024
MAX_TOTAL_CHARS = 32 * 1024
SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".kts", ".php", ".rb", ".cs",
    ".swift", ".dart", ".vue", ".sql",
}
SENSITIVE_PARTS = {
    ".env", ".env.local", ".env.production", "secrets", "secret",
    "credentials", "credential", "private", "certs",
}


def _safe_relative(root: Path, value: str) -> Path | None:
    """Return an in-repository regular file path, rejecting traversal."""
    if not value or Path(value).is_absolute():
        return None
    candidate = (root / value).resolve()
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if any(part.lower() in SENSITIVE_PARTS for part in relative.parts):
        return None
    if relative.name.lower() in SENSITIVE_PARTS:
        return None
    if candidate.suffix.lower() not in SOURCE_SUFFIXES:
        return None
    return candidate if candidate.is_file() else None


def _module_paths(modules: list[dict[str, Any]]) -> dict[str, str]:
    """Map dotted Python module names to repository-relative paths."""
    return {
        str(item["name"]): str(item["path"])
        for item in modules
        if isinstance(item, dict) and item.get("name") and item.get("path")
    }


def build_code_context(
    root: Path | str,
    repo_context: dict[str, Any],
    defects: list[dict[str, Any]],
    *,
    max_files: int = MAX_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_chars: int = MAX_TOTAL_CHARS,
) -> dict[str, Any]:
    """Collect bounded source evidence for defect files and direct neighbours.

    Defect paths are prioritized by the detector's existing order. For Python,
    direct imports of those files are added as useful neighbouring context.
    Files are read as text only; oversized, missing, binary and sensitive files
    are skipped. The returned rendering is suitable for an LLM prompt.
    """
    base = Path(root).resolve()
    modules = repo_context.get("modules", [])
    module_to_path = _module_paths(modules if isinstance(modules, list) else [])
    path_to_module = {path: name for name, path in module_to_path.items()}

    ordered: list[str] = []
    for defect in defects:
        if isinstance(defect, dict) and defect.get("file"):
            ordered.append(str(defect["file"]))

    # Add one-hop Python import neighbours for files already selected.
    for rel in list(ordered):
        module_name = path_to_module.get(rel)
        if not module_name:
            continue
        info = next(
            (m for m in modules if isinstance(m, dict) and m.get("path") == rel),
            None,
        )
        if not info:
            continue
        for imported in sorted(info.get("imports", [])):
            neighbour = module_to_path.get(str(imported))
            if neighbour:
                ordered.append(neighbour)

    rendered: list[str] = []
    included: list[str] = []
    total = 0
    seen: set[str] = set()
    truncated = False

    for rel in ordered:
        if rel in seen:
            continue
        seen.add(rel)
        if len(included) >= max_files:
            truncated = True
            break
        target = _safe_relative(base, rel)
        if target is None:
            continue
        try:
            raw = target.read_bytes()
        except OSError:
            continue
        if len(raw) > max_file_bytes:
            truncated = True
            raw = raw[:max_file_bytes]
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        remaining = max_total_chars - total
        if remaining <= 0:
            truncated = True
            break
        if len(source) > remaining:
            source = source[:remaining]
            truncated = True
        if not source:
            continue
        rendered.append(f"FILE: {rel}\n{source}")
        included.append(rel)
        total += len(source)
        if total >= max_total_chars:
            truncated = True
            break

    return {
        "files": included,
        "rendered": "\n\n".join(rendered) if rendered else "(No eligible source files were selected.)",
        "truncated": truncated,
        "characters": total,
    }
