#!/usr/bin/env python3
"""Verify that every version declaration in this repo agrees.

Sources checked:
  1. pyproject.toml     -> [project].version          (the single source)
  2. src/__init__.py    -> src.__version__            (imported, not parsed)
  3. docs/openapi.yaml  -> info.version
  4. git tag on HEAD    -> exact-match tag (vX.Y.Z), when on a release commit

Rationale for each rule:
  * `src.__version__` is computed at import time from pyproject.toml
    (`_read_version()`), so parsing the literal would compare a call
    expression and always fail. Import the module instead.
  * git is checked with `--exact-match`: `git describe --tags --abbrev=0`
    returns the NEAREST tag anywhere in history, which is a lower tag on an
    old branch or a feature branch -> false alarms. We only care whether the
    current commit IS a release tag, and whether that tag is ahead of
    pyproject (an orphan release).
  * An unreleased working commit (tag behind pyproject) is FINE and expected:
    the version is bumped in the release commit, then tagged.

Off-phone/CI note: no third-party deps. `tomllib` is stdlib (py3.11+) and we
import `src` directly, so this runs anywhere the repo runs.

Exit codes: 0 = aligned, 1 = mismatch, 2 = could not read a source.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _semver(value: str) -> tuple[int, int, int]:
    """Parse X.Y.Z (ignoring any local/build suffix). Raises ValueError."""
    core = value.split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3:
        raise ValueError(f"not semver: {value!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def read_pyproject() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def read_src_version() -> str:
    sys.path.insert(0, str(ROOT))
    import importlib

    src = importlib.import_module("src")
    return str(src.__version__)


def read_openapi() -> str:
    # The spec is real YAML; read it without a third-party parser by scanning
    # the info block for the version line (top-level `info:` -> `version:`).
    text = (ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8")
    in_info = False
    for line in text.splitlines():
        if line.startswith("info:"):
            in_info = True
            continue
        if in_info:
            if line and not line[0].isspace():
                break  # left the info block
            stripped = line.strip()
            if stripped.startswith("version:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("info.version not found in docs/openapi.yaml")


def read_git_tag_on_head() -> str | None:
    """Exact tag pointing at HEAD (without the leading 'v'), or None."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        tag = out.stdout.strip()
        return tag[1:] if tag.startswith("v") else tag
    except Exception:
        return None


def main() -> int:
    try:
        pyproject = read_pyproject()
        src = read_src_version()
        openapi = read_openapi()
        tag = read_git_tag_on_head()
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero
        print(f"ERR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"pyproject.toml -> {pyproject}")
    print(f"src.__version__ -> {src}")
    print(f"openapi.yaml   -> {openapi}")
    print(f"git tag (HEAD) -> {tag or '(none)'}")

    errors: list[str] = []
    if pyproject != src:
        errors.append(f"pyproject ({pyproject}) != src.__version__ ({src})")
    if pyproject != openapi:
        errors.append(f"pyproject ({pyproject}) != openapi ({openapi})")

    if tag:
        try:
            if _semver(tag) > _semver(pyproject):
                errors.append(
                    f"git tag ({tag}) > pyproject ({pyproject}) — orphan release"
                )
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        print("\nVERSION MISMATCH:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("\nAll versions aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
