"""Shared probes for the STRIDE PoC suite.

Kept deliberately small and stdlib-only so every STRIDE module can import it
on the phone gate. Nothing here patches production behaviour unless the
individual test asks for it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Secret-ish strings used by the Information-Disclosure probes.
# ---------------------------------------------------------------------------

#: A realistic-looking, NON-functional GitHub token. Only used to prove that a
#: scanner detects / does not detect it, and that a surface never echoes it.
#: Never a live credential (the repo's adversarial suite already forbids real
#: ones; this mirrors that fixture style).
FAKE_GH_TOKEN = "ghp_" + "A" * 36
FAKE_AWS_KEY = "AKIA" + "B" * 16

#: A path that must NEVER be readable through the confined tool executor.
VICTIM_RELATIVE = "../../../../../../etc/passwd"


def repo_root() -> Path:
    """The checkout root (this file is tests/security/stride/helpers.py)."""
    return Path(__file__).resolve().parents[3]


def access_guard(**kwargs: Any) -> Any:
    """Build an AccessGuard, skipping nothing — caller decides skip.

    Accepts ``rate``/``window`` as a convenience and turns them into a
    ``RateLimiter`` (the guard takes ``limiter=``, not ``limit=``). Any other
    keyword passes straight through to ``AccessGuard``.

    Imported lazily so a missing module surfaces as an ImportError the test
    can turn into a skip, not a collection crash.
    """
    from src.security.access import AccessGuard, RateLimiter

    rate = kwargs.pop("rate", None)
    window = kwargs.pop("window", 60.0)
    if rate is not None and "limiter" not in kwargs:
        kwargs["limiter"] = RateLimiter(rate=int(rate), window=float(window))
    return AccessGuard(**kwargs)


def make_env(**overrides: str) -> dict[str, str]:
    """A clean env mapping for AccessGuard.from_env tests (no os.environ leak)."""
    base: dict[str, str] = {}
    base.update(overrides)
    return base


def resolve_in_root(root: Path, raw: str) -> Path | None:
    """Return the resolved path if it stays inside ``root``, else ``None``.

    This mirrors :meth:`src.tools.executor.LocalToolExecutor._resolve` so a
    traversal probe can assert the *policy* independently of the executor's
    exception type.
    """
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        return None
    return resolved


def env_without(*names: str) -> dict[str, str]:
    """A copy of os.environ with the given names removed (for import tests)."""
    return {k: v for k, v in os.environ.items() if k not in names}


__all__ = [
    "FAKE_GH_TOKEN",
    "FAKE_AWS_KEY",
    "VICTIM_RELATIVE",
    "repo_root",
    "access_guard",
    "make_env",
    "resolve_in_root",
    "env_without",
]
