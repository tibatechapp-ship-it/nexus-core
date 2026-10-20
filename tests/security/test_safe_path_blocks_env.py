"""Regression guards for C2 — ``safe_path`` must refuse sensitive files.

Before the fix, ``unified_agent.safe_path`` only checked that a resolved path
stayed inside the project root.  ``.env`` lives inside the root, so
``GET /api/workspace/file?path=.env`` returned the live provider keys.  The
fix adds the shared ``is_sensitive_file`` deny-list (already used by the tool
executor) so the two guards can never drift apart.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_safe_path():
    """Import ``safe_path`` from the repo-root ``unified_agent`` by path."""
    spec = importlib.util.spec_from_file_location("_ua_root", _ROOT / "unified_agent.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.safe_path


@pytest.fixture(scope="module")
def safe_path():
    return _load_safe_path()


@pytest.mark.parametrize(
    "secret",
    [".env", ".env.local", ".env.prod", ".env.production", ".env.dev"],
)
def test_env_files_are_refused(safe_path, secret):
    """Every ``.env`` flavour is a credential store and must be blocked."""
    with pytest.raises(ValueError, match="sensitive"):
        safe_path(secret)


def test_ssh_private_key_is_refused(safe_path):
    """A key file inside the root is still a secret."""
    with pytest.raises(ValueError, match="sensitive"):
        safe_path(".ssh/id_rsa")


def test_benign_file_still_resolves(safe_path):
    """README is not sensitive — the guard must not over-block."""
    resolved = safe_path("README.md")
    assert resolved.name == "README.md"
    assert resolved.is_relative_to(_ROOT)


def test_traversal_is_still_refused(safe_path):
    """The original boundary check must survive the sensitivity addition."""
    with pytest.raises(ValueError, match="outside project"):
        safe_path("../etc/passwd")


def test_env_example_stays_readable(safe_path):
    """.env.example documents variable NAMES only — never a live value."""
    resolved = safe_path(".env.example")
    assert resolved.name == ".env.example"
