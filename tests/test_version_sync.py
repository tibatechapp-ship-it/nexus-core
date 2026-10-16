"""Version single-source invariant.

The project keeps ONE authoritative version in ``pyproject.toml``.
``src.__version__`` reads it at import (no hand-kept mirror), and the console +
``/api/health`` read it live. This test fails if ``src`` ever drifts back to a
hard-coded literal, and records the version for humans in the changelog.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import src

_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_src_version_matches_pyproject() -> None:
    assert src.__version__ == _pyproject_version()


def test_changelog_documents_current_version() -> None:
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## v{_pyproject_version()}" in changelog
