#!/usr/bin/env python3
"""Repository housekeeping — prune caches, backups and temp files safely.

Dry-run BY DEFAULT: nothing is deleted until you pass ``--apply``. Even then a
hard-protection list refuses to touch source, tests, the runtime data dir,
``genome.json`` or ``.git`` — housekeeping must never be why a build broke.

Usage:
    python3 scripts/cleanup.py                 # report what WOULD be removed
    python3 scripts/cleanup.py --apply         # actually remove
    python3 scripts/cleanup.py --root /path    # operate on another tree
    python3 scripts/cleanup.py --json          # machine-readable report
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# Directories that prune one level deep: any of these found ANYWHERE is fair game.
_PRUNE_DIRS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")

# File-name globs pruned anywhere in the tree.
_PRUNE_GLOBS = ("*.pyc", "*.pyo", "*.bak", "*.bak-*", "*.tmp", "*.orig", "*.rej")

# Never descend into these (their contents are not ours to clean).
_SKIP_DIR_NAMES = (".git", "node_modules", ".venv", "venv")

# Path fragments that are OFF-LIMITS even if a glob matches (segment-aware).
_PROTECTED_PARTS = ("src", "tests")

# Repo-control dotfiles: never prune a backup of one (e.g. ``.gitignore.bak``).
_PROTECTED_STEMS = (".gitignore", ".env", ".dockerignore", ".gitattributes")


def _repo_root() -> Path:
    """The repository root (this script lives in ``<root>/scripts``)."""
    return Path(__file__).resolve().parents[1]


def _protected_stem(name: str) -> bool:
    """True when ``name`` is (or backs up) a repo-control dotfile."""
    base = name
    for marker in (".bak-", ".bak", ".orig", ".rej", ".tmp"):
        index = base.find(marker)
        if index > 0:
            base = base[:index]
            break
    return base in _PROTECTED_STEMS


def _is_protected(path: Path, root: Path) -> bool:
    """True when ``path`` must never be deleted."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True  # outside the tree — never ours
    if not parts:
        return True
    if _protected_stem(path.name):
        return True
    if parts[0] == ".git":
        return True
    if parts[0] == "data" and (len(parts) == 1 or path.name == "genome.json"):
        return True
    if any(segment in _PROTECTED_PARTS for segment in parts[:-1]):
        return True
    return False


def _candidates(root: Path) -> List[Path]:
    """Every path eligible for pruning, newest-safe order (files then dirs)."""
    files: List[Path] = []
    dirs: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        # Prune traversal (in place, so os.walk honours it).
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        if _is_protected(here, root) and here != root:
            dirnames[:] = []
            continue
        for name in list(dirnames):
            if name in _PRUNE_DIRS:
                target = here / name
                if not _is_protected(target, root):
                    dirs.append(target)
                dirnames.remove(name)
        for name in filenames:
            candidate = here / name
            if _is_protected(candidate, root):
                continue
            if any(candidate.match(glob) for glob in _PRUNE_GLOBS):
                files.append(candidate)
    return files + dirs


def _size_of(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for sub in path.rglob("*"):
        if sub.is_file():
            try:
                total += sub.stat().st_size
            except OSError:
                pass
    return total


def _log_path(root: Path) -> Path:
    return Path(os.environ.get("NEXUS_CLEANUP_LOG", str(root / "data" / "cleanup.log")))


def _append_log(root: Path, lines: Iterable[str]) -> None:
    """Best-effort log; a logging failure never fails the run."""
    try:
        path = _log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
    except OSError:
        pass


def _remove(path: Path) -> bool:
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError:
        return False


def run(root: Path, *, apply: bool) -> Dict[str, object]:
    """Plan (and optionally perform) the cleanup; return a report dict."""
    targets = _candidates(root)
    report_targets: List[Tuple[str, int]] = []
    freed = 0
    removed: List[str] = []
    for target in targets:
        size = _size_of(target)
        rel = str(target.resolve().relative_to(root.resolve()))
        report_targets.append((rel, size))
        if apply and _remove(target):
            removed.append(rel)
            freed += size
    return {
        "root": str(root),
        "applied": apply,
        "count": len(targets),
        "bytes": sum(size for _, size in report_targets),
        "removed": removed,
        "targets": report_targets,
    }


def _render(report: Dict[str, object]) -> str:
    mode = "APPLIED" if report["applied"] else "DRY-RUN (nothing removed)"
    lines = [
        f"cleanup: {mode}",
        f"root    : {report['root']}",
        f"targets : {report['count']}",
        f"bytes   : {report['bytes']}",
    ]
    for rel, size in report["targets"]:  # type: ignore[misc]
        lines.append(f"  - {rel} ({size} B)")
    if not report["applied"]:
        lines.append("pass --apply to remove them")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune caches, backups and temp files.")
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    parser.add_argument("--root", default=None, help="tree to clean (default: repo root)")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else _repo_root()
    if not root.is_dir():
        print(f"cleanup: not a directory: {root}", file=sys.stderr)
        return 2

    report = run(root, apply=args.apply)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render(report))

    _append_log(
        root,
        [
            f"cleanup applied={report['applied']} count={report['count']} "
            f"bytes={report['bytes']} root={report['root']}"
        ]
        + [f"  removed {rel}" for rel in report["removed"]]  # type: ignore[union-attr]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
