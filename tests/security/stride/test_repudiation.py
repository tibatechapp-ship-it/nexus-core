"""STRIDE — **R**epudiation: denying an action happened / no proof of action.

Attack surface for nexus-core:

* The access guard can write an audit trail (``NEXUS_AUDIT_LOG``). If audit is
  OFF by default, a mutating action leaves **no record** — the caller can deny
  it. And when ON, the row must carry enough to attribute the action (method,
  path, client, status, timestamp).
* The council writes a debate trace (``data/council_trace.jsonl``) — if a
  member's vote is not recorded with the outcome, the council can disown a
  verdict.
* The training/lesson ledger must record *who did what*; a lesson without an
  agent id cannot be attributed.

Each test asserts that an *auditable* action actually leaves a row an
investigator could use — and flags where it does not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.security.stride import helpers as H

CATEGORY = "Repudiation"


# ---------------------------------------------------------------------------
# R1 — when audit is enabled, a mutating call writes an attributable row
# ---------------------------------------------------------------------------
def test_r1_audit_records_attributable_rows(tmp_path: Path) -> None:
    """EXPLOIT: attacker performs a destructive write then claims "I never did".

    DEFENCE (when NEXUS_AUDIT_LOG is set): one JSON line per call carrying
    ts/method/path/client/status/allowed. The PoC enables audit at a temp path,
    records a refused and an allowed call, and asserts both lines are
    attributable.
    """
    import src.security.access as access_mod

    log = tmp_path / "audit.jsonl"
    guard = access_mod.AccessGuard(
        token="t", audit=access_mod.AuditLog(log)
    )
    denied = guard.check("POST", "/api/genome/import", {"x-auth-token": "bad"})
    guard.record(denied, "POST", "/api/genome/import", client="9.9.9.9",
                 status=401)
    ok = guard.check("POST", "/api/genome/import", {"x-auth-token": "t"})
    guard.record(ok, "POST", "/api/genome/import", client="9.9.9.9", status=200)

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    for row in rows:
        for field in ("ts", "event", "method", "path", "client", "status",
                      "allowed"):
            assert field in row, f"audit row missing {field!r}: {row}"
    assert rows[0]["allowed"] is False and rows[0]["status"] == 401
    assert rows[1]["allowed"] is True and rows[1]["status"] == 200


# ---------------------------------------------------------------------------
# R2 — audit-off is silent; the gap must be explicit, not a false "logged"
# ---------------------------------------------------------------------------
def test_r2_audit_off_is_documented_not_silent_success(tmp_path: Path) -> None:
    """EXPLOIT: operator believes everything is logged and denies nothing; but
    audit defaults OFF, so nothing is on disk.

    DEFENCE/PoC: prove the default has NO path (enabled False) so the *gap* is
    a known, explicit state (surfaced in ``/api/status`` guard.audit=None) —
    a truth we can document, not a silent lie that auditing happened.
    """
    guard = H.access_guard(token="t")  # no audit kwarg -> default AuditLog()
    assert guard.audit.enabled is False
    assert guard.stats()["audit"] is None
    row = guard.record(guard.check("POST", "/x", {}), "POST", "/x")
    # The record is still returned for callers to log elsewhere, but no file.
    assert row["event"] == "http"


# ---------------------------------------------------------------------------
# R3 — audit log never contains the secret token (attribution without leak)
# ---------------------------------------------------------------------------
def test_r3_audit_never_records_the_token(tmp_path: Path) -> None:
    """EXPLOIT: auditor reads the log for evidence and finds the admin token —
    audit becomes an exfiltration channel.

    DEFENCE: the audit row records *allowed/denied*, never the credential.
    """
    import src.security.access as access_mod

    log = tmp_path / "audit.jsonl"
    secret = "super-secret-token-value"
    guard = access_mod.AccessGuard(token=secret, audit=access_mod.AuditLog(log))
    dec = guard.check("POST", "/api/chat", {"x-auth-token": secret})
    guard.record(dec, "POST", "/api/chat", client="127.0.0.1", status=200)
    blob = log.read_text(encoding="utf-8")
    assert secret not in blob, "the auth token leaked into the audit log"
    assert "x-auth-token" not in blob or secret not in blob


# ---------------------------------------------------------------------------
# R4 — a council verdict is traceable to per-member stances
# ---------------------------------------------------------------------------
def test_r4_council_vote_is_traceable() -> None:
    """EXPLOIT: after an unpopular council verdict a member says "not my vote".

    DEFENCE: the debate must be reducible to per-member stances (who approved,
    who rejected) so a verdict is attributable. PoC drives the pure stance
    helper used by the genome bridge.
    """
    pytest.importorskip("src.novamind.council.council")
    try:
        from src.novamind.council.council import judgement_stances
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"council unavailable: {exc}")

    inference = {
        "analyst": {"standing_delta": 1},
        "critic": {"standing_delta": -1},
        "profiler": {"standing_delta": 0},
    }
    stances = judgement_stances(inference)
    assert isinstance(stances, dict)
    # Every voting member must appear (an unattributable vote = repudiation).
    assert set(stances) == {"analyst", "critic", "profiler"}
    assert stances["analyst"] == "approve"
    assert stances["critic"] == "reject"
