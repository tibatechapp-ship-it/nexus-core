#!/usr/bin/env python3
"""Verify that every version declaration in this repo agrees.

Sources checked:
  1. pyproject.toml     -> [project].version          (the single source)
  2. src/__init__.py    -> src.__version__            (imported, not parsed)
  3. docs/openapi.yaml  -> info.version
  4. git tag on HEAD    -> release tag (vX.Y.Z) via `git tag --points-at HEAD`

Rationale for each rule:
  * `src.__version__` is computed at import time from pyproject.toml
    (`_read_version()`), so parsing the literal would compare a call
    expression and always fail. Import the module instead.
  * git is checked with `git tag --points-at HEAD`, NOT `git describe
    --tags --exact-match`: describe returns an ARBITRARY tag when several point
    at the same commit (a `backup/...` maintenance tag alongside the real
    release tag), so the orphan-release check could read the wrong string. We
    list every tag at HEAD and keep the semver `v`-tags only.
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


def _release_version(tag: str) -> str | None:
    """Return the X.Y.Z of a release tag (``vX.Y.Z``), or None otherwise.

    Only ``v``-prefixed tags that parse as semver count as release tags. This
    ignores maintenance fixtures such as ``backup/...`` so they can never be
    mistaken for the released version.
    """
    if not tag.startswith("v"):
        return None
    try:
        _semver(tag[1:])
    except ValueError:
        return None
    return tag[1:]


def read_git_tag_on_head() -> str | None:
    """The release tag (``vX.Y.Z``) pointing at HEAD, or None.

    ``git describe --tags --exact-match`` returns an ARBITRARY tag when several
    point at the same commit (e.g. a ``backup/...`` fixture tag alongside the
    real ``vX.Y.Z``), so the orphan-release guard could read the wrong one and
    fail silently. ``git tag --points-at HEAD`` lists them all; we pick the
    semver ``v``-tag deterministically.
    """
    try:
        out = subprocess.run(
            ["git", "tag", "--points-at", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
    except Exception:
        return None
    versions = [
        v for v in (_release_version(t) for t in out.stdout.split()) if v
    ]
    # Deterministic: the highest release tag wins if several point at HEAD.
    if not versions:
        return None
    return max(versions, key=_semver)


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
            if _semver(tag) != _semver(pyproject):
                # Both directions matter:
                #   tag > pyproject = orphan release (published a tag without bumping).
                #   tag < pyproject = un-tagged bump (bumped pyproject without tagging).
                # Either way, the repo's single-source invariant is broken; the
                # fix is the same (align them), so report it once with the
                # direction spelled out.
                direction = "orphan release" if _semver(tag) > _semver(pyproject) else "un-tagged version bump"
                errors.append(
                    f"git tag ({tag}) != pyproject ({pyproject}) — {direction}"
                )
        except ValueError as exc:
            errors.append(str(exc))
    else:
        errors.append(
            f"no release tag on HEAD — pyproject is {pyproject} but no v{pyproject} tag exists"
        )

    if errors:
        print("\nVERSION MISMATCH:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("\nAll versions aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
