"""Version single-source invariant.

The project keeps one authoritative version and mirrors it in two places that
are easy to drift apart: ``pyproject.toml`` and ``src/__init__.py``. The console
and ``/api/health`` read the runtime value live; the changelog records it for
humans. This test fails the moment any of the three disagree.
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
