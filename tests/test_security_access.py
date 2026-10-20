"""Tests for the HTTP access guard (``src/security/access.py``).

Hermetic: an injected clock drives the rate limiter and the audit log, and
every audit destination is a ``tmp_path``.  No server, no network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.security.access import (
    AUDIT_MAX_BYTES,
    DEFAULT_RATE,
    DEFAULT_WINDOW,
    AccessGuard,
    AuditLog,
    Decision,
    MUTATING_METHODS,
    RateLimiter,
    _float_env,
    _int_env,
    _is_off,
)


class _Clock:
    """A hand-cranked monotonic clock."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


class _NoGet:
    """A header bag with no ``get`` — models a malformed request object."""


# ── plumbing ─────────────────────────────────────────────────────────


def test_is_off_accepts_the_usual_spellings() -> None:
    for value in ("", "0", "off", "OFF", " no ", "False", "none"):
        assert _is_off(value) is True
    for value in ("on", "1", "/tmp/audit.jsonl", "yes"):
        assert _is_off(value) is False


def test_float_env_defaults_and_survives_junk() -> None:
    assert _float_env(None, 7.5) == 7.5          # unset
    assert _float_env(" 2.5 ", 7.5) == 2.5       # parsed
    assert _float_env("soon", 7.5) == 7.5        # junk -> default


def test_int_env_defaults_and_survives_junk() -> None:
    assert _int_env(None, 9) == 9
    assert _int_env(" 12 ", 9) == 12
    assert _int_env("12.7", 9) == 12             # floats are tolerated
    assert _int_env("many", 9) == 9


def test_decision_defaults_to_allowed() -> None:
    d = Decision(allowed=True)
    assert (d.status, d.error, d.retry_after) == (200, "", 0.0)


# ── rate limiter ─────────────────────────────────────────────────────


def test_limiter_is_disabled_by_a_nonpositive_knob() -> None:
    for rate, window in ((0, 60.0), (-1, 60.0), (10, 0.0)):
        lim = RateLimiter(rate, window, clock=_Clock())
        assert lim.enabled is False
        assert lim.allow("k") == 0.0            # always free when disabled


def test_limiter_spends_the_budget_then_reports_the_wait() -> None:
    clock = _Clock()
    lim = RateLimiter(2, 10.0, clock=clock)
    assert lim.enabled is True
    assert lim.allow("a") == 0.0                # 1st
    assert lim.allow("a") == 0.0                # 2nd
    wait = lim.allow("a")                       # 3rd — over budget
    assert wait == 10.0                         # full window left
    clock.tick(4.0)
    assert lim.allow("a") == pytest.approx(6.0)  # partial window left
    assert lim.allow("b") == 0.0                # a different key is independent


def test_limiter_window_rolls_over_and_reset_clears() -> None:
    clock = _Clock()
    lim = RateLimiter(1, 10.0, clock=clock)
    assert lim.allow("a") == 0.0
    assert lim.allow("a") == 10.0
    clock.tick(10.0)                            # window elapsed exactly
    assert lim.allow("a") == 0.0
    lim.reset()
    assert lim.allow("a") == 0.0


# ── audit log ────────────────────────────────────────────────────────


def test_audit_write_without_a_path_only_builds_the_record() -> None:
    log = AuditLog(clock=_Clock(5.0))
    assert log.enabled is False
    row = log.write("http", path="/api/x", status=200)
    assert row == {"ts": 5.0, "event": "http", "path": "/api/x", "status": 200}


def test_audit_writes_jsonl_and_creates_the_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "audit.jsonl"
    log = AuditLog(target, clock=_Clock(1.0))
    assert log.enabled is True
    log.write("http", path="/api/a")
    log.write("http", path="/api/b")
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"path": "/api/a"' in lines[0] and '"path": "/api/b"' in lines[1]


def test_audit_rotates_once_past_max_bytes(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    log = AuditLog(target, max_bytes=10, clock=_Clock(1.0))
    log.write("http", path="/api/first")
    assert target.exists()
    log.write("http", path="/api/second")       # size > 10 -> rotate first
    assert (tmp_path / "audit.jsonl.1").exists()
    assert '"path": "/api/second"' in target.read_text(encoding="utf-8")


def test_audit_swallows_io_errors(tmp_path: Path) -> None:
    blocker = tmp_path / "afile"
    blocker.write_text("not a directory", encoding="utf-8")
    log = AuditLog(blocker / "audit.jsonl", clock=_Clock(1.0))
    row = log.write("http", path="/api/x")      # mkdir fails -> swallowed
    assert row["path"] == "/api/x"


# ── guard: configuration ─────────────────────────────────────────────


def test_from_env_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-argument form reads ``os.environ`` (rather than an injected mapping)."""
    monkeypatch.setenv("NEXUS_AUTH_TOKEN", "from-environ")
    guard = AccessGuard.from_env()
    assert guard.auth_enabled is True
    assert guard.rate_enabled is True


def test_from_env_defaults_are_local_friendly() -> None:
    guard = AccessGuard.from_env({})
    assert guard.auth_enabled is False          # token unset -> no auth
    assert guard.rate_enabled is True           # generous limit is on
    assert guard.limiter is not None
    assert (guard.limiter.rate, guard.limiter.window) == (DEFAULT_RATE,
                                                          DEFAULT_WINDOW)
    assert guard.audit.enabled is False          # no surprise disk writes
    assert guard.stats()["methods"] == sorted(MUTATING_METHODS)


def test_from_env_honours_every_knob(tmp_path: Path) -> None:
    clock = _Clock()
    guard = AccessGuard.from_env({
        "NEXUS_AUTH_TOKEN": "  s3cret  ",
        "NEXUS_RATE_LIMIT": "5",
        "NEXUS_RATE_WINDOW": "30",
        "NEXUS_AUDIT_LOG": str(tmp_path / "audit.jsonl"),
    }, clock=clock)
    assert guard.token == "s3cret"              # trimmed
    assert guard.auth_enabled is True
    assert (guard.limiter.rate, guard.limiter.window) == (5, 30.0)
    assert guard.audit.enabled is True
    stats = guard.stats()
    assert stats["auth"] is True and stats["rate"] == 5 and stats["window"] == 30.0
    assert stats["audit"].endswith("audit.jsonl")


def test_from_env_can_disable_everything() -> None:
    guard = AccessGuard.from_env({
        "NEXUS_RATE_LIMIT": "0",
        "NEXUS_AUDIT_LOG": "off",
        "NEXUS_RATE_WINDOW": "nonsense",
    })
    assert guard.auth_enabled is False
    assert guard.rate_enabled is False
    assert guard.audit.enabled is False
    stats = guard.stats()
    assert stats["rate"] == 0 and stats["window"] == 0.0
    assert stats["audit"] is None


def test_guard_without_a_limiter_is_free() -> None:
    guard = AccessGuard(limiter=None)
    assert guard.rate_enabled is False
    assert guard.check("POST", "/api/x", {}, client="127.0.0.1").allowed is True
    assert guard.stats()["rate"] == 0


# ── guard: decisions ─────────────────────────────────────────────────


def test_reads_never_need_a_token() -> None:
    guard = AccessGuard(token="s3cret")
    for verb in ("GET", "HEAD", "OPTIONS", "get"):
        assert guard.check(verb, "/api/status", {}).allowed is True


def test_mutating_calls_require_the_header_when_a_token_is_set() -> None:
    guard = AccessGuard(token="s3cret")
    missing = guard.check("POST", "/api/chat", {})
    assert (missing.allowed, missing.status) == (False, 401)
    assert "x-auth-token" in missing.error
    wrong = guard.check("POST", "/api/chat", {"x-auth-token": "nope"})
    assert (wrong.allowed, wrong.status) == (False, 401)
    ok = guard.check("POST", "/api/chat", {"x-auth-token": "s3cret"})
    assert ok.allowed is True


def test_a_header_bag_without_get_is_rejected() -> None:
    guard = AccessGuard(token="s3cret")
    denied = guard.check("DELETE", "/api/x", _NoGet())  # type: ignore[arg-type]
    assert (denied.allowed, denied.status) == (False, 401)


def test_rate_limit_refuses_with_a_retry_after() -> None:
    clock = _Clock()
    guard = AccessGuard(limiter=RateLimiter(1, 45.0, clock=clock))
    assert guard.check("POST", "/api/training/run", {}, client="127.0.0.1").allowed
    limited = guard.check("POST", "/api/training/run", {}, client="127.0.0.1")
    assert (limited.allowed, limited.status) == (False, 429)
    assert limited.retry_after == 45.0
    assert limited.error == "rate limit exceeded"
    # another client still has its own budget (both loopback: auth is off)
    assert guard.check("POST", "/api/training/run", {}, client="127.0.0.2").allowed


def test_a_clientless_request_still_counts() -> None:
    guard = AccessGuard(limiter=RateLimiter(1, 5.0, clock=_Clock()))
    assert guard.check("POST", "/api/x", {}, client="127.0.0.1").allowed is True
    assert guard.check("POST", "/api/x", {}, client="127.0.0.1").allowed is False


def test_token_is_checked_before_the_rate_budget() -> None:
    guard = AccessGuard(token="s3cret",
                        limiter=RateLimiter(1, 5.0, clock=_Clock()))
    first = guard.check("POST", "/api/x", {"x-auth-token": "s3cret"})
    assert first.allowed is True
    rejected = guard.check("POST", "/api/x", {})       # bad token AND over budget
    assert rejected.status == 401                      # auth wins


def test_record_writes_a_row_with_defaults() -> None:
    guard = AccessGuard(limiter=None)
    row = guard.record(Decision(allowed=True), "post", "/api/chat")
    assert row["event"] == "http"
    assert (row["method"], row["path"], row["client"], row["status"]) == (
        "POST", "/api/chat", "-", 200)
    assert row["allowed"] is True


def test_record_keeps_the_client_when_known(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    guard = AccessGuard(limiter=None, audit=AuditLog(target))
    guard.record(Decision(False, 429, "rate limit exceeded"), "POST",
                 "/api/x", client="127.0.0.1")
    text = target.read_text(encoding="utf-8")
    assert '"client": "127.0.0.1"' in text and '"status": 429' in text


def test_max_bytes_default_is_one_megabyte() -> None:
    assert AUDIT_MAX_BYTES == 1_000_000
    assert AuditLog().max_bytes == AUDIT_MAX_BYTES


def test_stats_never_leaks_the_token() -> None:
    guard = AccessGuard(token="s3cret", limiter=RateLimiter(3, 9.0, clock=_Clock()))
    stats: Dict[str, Any] = guard.stats()
    assert "s3cret" not in repr(stats)
    assert stats["header"] == "x-auth-token"
    assert stats["methods"] == ["DELETE", "PATCH", "POST", "PUT"]


def test_custom_methods_narrow_the_gate() -> None:
    guard = AccessGuard(token="s3cret", methods=["post"])
    assert guard.check("GET", "/api/x", {}).allowed is True
    assert guard.check("PUT", "/api/x", {}).allowed is True   # not in the set
    assert guard.check("POST", "/api/x", {}).allowed is False


def test_audit_is_shared_across_checks(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    guard = AccessGuard(token="s3cret", limiter=None, audit=AuditLog(target))
    guard.record(guard.check("POST", "/api/a", {"x-auth-token": "s3cret"}),
                 "POST", "/api/a")
    guard.record(guard.check("POST", "/api/b", {}), "POST", "/api/b")
    lines: List[str] = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"status": 200' in lines[0] and '"status": 401' in lines[1]


def test_record_can_carry_the_observed_status() -> None:
    """``**fields`` overrides the predicted status with what really happened."""
    guard = AccessGuard(limiter=None)
    row = guard.record(Decision(allowed=True), "get", "/api/nope", status=404)
    assert (row["status"], row["method"], row["allowed"]) == (404, "GET", True)
