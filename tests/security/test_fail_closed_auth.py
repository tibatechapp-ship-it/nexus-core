"""Regression guards for C3 — the guard must fail CLOSED off loopback.

Before the fix, a tokenless :class:`AccessGuard` allowed mutating requests from
*any* client IP.  A gateway bound to ``0.0.0.0`` (the standalone engine,
``unified_agent.py``) therefore accepted anonymous writes from the whole LAN —
and, chained with C2, an anonymous ``.env`` read.

Policy under test:
  * loopback + no token        -> allow (local dev)
  * non-loopback + no token    -> 401 (fail closed)
  * non-loopback + wrong token -> 401
  * non-loopback + right token -> allow
  * loopback + wrong token     -> 401 (a bad token is still a bad token)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from security.access import AccessGuard, is_loopback  # noqa: E402

_REMOTE = "203.0.113.5"   # TEST-NET-3, never a real host
_LOCAL = "127.0.0.1"


def test_loopback_detection():
    """127.0.0.0/8 and ::1 are loopback; anything else is not."""
    assert is_loopback("127.0.0.1")
    assert is_loopback("127.0.0.5")
    assert is_loopback("::1")
    assert not is_loopback("10.0.0.5")
    assert not is_loopback("")
    assert not is_loopback("not-an-ip")


# ── tokenless gateway ───────────────────────────────────────────────────────

def test_tokenless_loopback_is_allowed():
    guard = AccessGuard(token="")
    decision = guard.check("POST", "/api/chat", {}, client=_LOCAL)
    assert decision.allowed


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_tokenless_remote_is_refused(method):
    guard = AccessGuard(token="")
    decision = guard.check(method, "/api/workspace/file", {}, client=_REMOTE)
    assert not decision.allowed
    assert decision.status == 401


def test_tokenless_unknown_client_fails_closed():
    """A missing client value must not silently open the gate."""
    guard = AccessGuard(token="")
    assert not guard.check("POST", "/x", {}, client="").allowed


def test_reads_stay_free_regardless_of_client():
    guard = AccessGuard(token="")
    assert guard.check("GET", "/api/health", {}, client=_REMOTE).allowed


# ── token-protected gateway ─────────────────────────────────────────────────

def test_remote_with_wrong_token_is_refused():
    guard = AccessGuard(token="s3cret")
    decision = guard.check("POST", "/api/chat", {"x-auth-token": "nope"},
                           client=_REMOTE)
    assert not decision.allowed and decision.status == 401


def test_remote_with_right_token_is_allowed():
    guard = AccessGuard(token="s3cret")
    decision = guard.check("POST", "/api/chat", {"x-auth-token": "s3cret"},
                           client=_REMOTE)
    assert decision.allowed


def test_loopback_with_wrong_token_is_refused():
    """A wrong token is still wrong, even from localhost."""
    guard = AccessGuard(token="s3cret")
    decision = guard.check("POST", "/api/chat", {"x-auth-token": "nope"},
                           client=_LOCAL)
    assert not decision.allowed and decision.status == 401
