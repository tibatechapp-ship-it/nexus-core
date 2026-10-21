"""Tests for scripts/retention.py — the production retention entry point.

``scripts/*`` is coverage-omitted, but the dry-run-vs-apply contract and the
env resolution are behaviour worth locking: a dry-run must be read-only and an
apply must actually prune.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load():
    path = _REPO / "scripts" / "retention.py"
    spec = importlib.util.spec_from_file_location("retention_script", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["retention_script"] = mod
    spec.loader.exec_module(mod)
    return mod


retention = _load()


@pytest.fixture()
def seeded_db(tmp_path):
    """A memory DB with 3 old episodes (40d) and 2 recent ones.

    Timestamps are relative to the REAL clock because ``run()`` opens the
    manager with its default clock — seeding 1e9 would make everything look
    ancient and the age filter would delete all 5.
    """
    import time

    from src.memory.manager import MemoryManager

    db = tmp_path / "mem.db"
    now = time.time()
    mgr = MemoryManager(str(db))
    old = now - 40 * 86400
    for i in range(3):
        mgr.episodic.record("coder", f"old {i}", "r", timestamp=old + i)
    for i in range(2):
        mgr.episodic.record("coder", f"new {i}", "r", timestamp=now - i)
    mgr.close()
    return str(db), now


def test_dry_run_is_read_only(seeded_db):
    db, _ = seeded_db
    before = retention.run(apply=False, max_age_days=30, max_episodes=None, db_path=db)
    assert before["applied"] is False
    assert before["before"] == 5
    assert before["removed"] == 3
    assert before["after"] == 5, "a dry-run must not delete anything"


def test_apply_removes_old_episodes(seeded_db):
    db, _ = seeded_db
    rep = retention.run(apply=True, max_age_days=30, max_episodes=None, db_path=db)
    assert rep["removed"] == 3
    assert rep["after"] == 2


def test_max_episodes_cap(seeded_db):
    db, _ = seeded_db
    rep = retention.run(apply=True, max_age_days=None, max_episodes=4, db_path=db)
    assert rep["after"] == 4


def test_no_policy_reports_error(monkeypatch):
    monkeypatch.delenv("NEXUS_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("NEXUS_RETENTION_EPISODES", raising=False)
    rep = retention.run(apply=True, max_age_days=None, max_episodes=None)
    assert rep["error"] is not None
    assert rep["removed"] == 0


def test_env_fills_missing_policy(monkeypatch, seeded_db):
    db, _ = seeded_db
    monkeypatch.setenv("NEXUS_RETENTION_DAYS", "30")
    rep = retention.run(apply=True, max_age_days=None, max_episodes=None, db_path=db)
    assert rep["max_age_days"] == 30.0
    assert rep["removed"] == 3


def test_non_positive_cap_is_unset():
    assert retention.resolve_policy(0, -5) == (None, None)
    assert retention.resolve_policy(30, 100) == (30.0, 100)
