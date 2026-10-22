#!/usr/bin/env python3
"""Sync ``info.version`` in ``docs/openapi.yaml`` with ``pyproject.toml``.

Run as a pre-test step in ``make check`` so the spec cannot drift from the
code. Only the version line inside the top-level ``info:`` block is touched —
any other ``version:`` key (e.g. inside request/response schemas) is left alone.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
SPEC = ROOT / "docs" / "openapi.yaml"


def read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def read_spec_version(text: str) -> str | None:
    """Return the version inside the top-level info: block, or None."""
    in_info = False
    for line in text.splitlines():
        stripped = line.rstrip()
        if re.match(r"^info:\s*$", stripped):
            in_info = True
            continue
        if in_info:
            # Leaving the info block: another top-level key at column 0
            if stripped and not stripped.startswith(" ") and not stripped.startswith("\t"):
                return None
            match = re.match(r'^\s+version:\s*["\']?([\d.]+)["\']?\s*$', stripped)
            if match:
                return match.group(1)
    return None


def main() -> int:
    version = read_pyproject_version()
    spec_text = SPEC.read_text(encoding="utf-8")
    current = read_spec_version(spec_text)
    if current is None:
        print(f"ERROR: no info.version found in {SPEC}", file=sys.stderr)
        return 1
    if current == version:
        print(f"OK: openapi.yaml version already {version}")
        return 0
    # Replace only the info-block version line
    new_lines: list[str] = []
    in_info = False
    replaced = False
    for line in spec_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip()
        if re.match(r"^info:\s*$", stripped):
            in_info = True
            new_lines.append(line)
            continue
        if in_info and not replaced:
            match = re.match(r'^(\s+version:\s*)["\']?[\d.]+["\']?(\s*)$', stripped)
            if match:
                new_lines.append(f"{match.group(1)}{version}{match.group(2)}\n")
                replaced = True
                continue
        new_lines.append(line)
    if not replaced:
        print(f"ERROR: failed to replace version in {SPEC}", file=sys.stderr)
        return 1
    SPEC.write_text("".join(new_lines), encoding="utf-8")
    print(f"OK: openapi.yaml version {current} → {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
