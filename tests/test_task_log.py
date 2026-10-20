"""Tests for the maintenance task ledger (pure, stdlib-only).

Everything here is hermetic: ``NEXUS_TASK_LOG`` is pointed at a per-test temp
file, so the repo's real ``data/task_log.jsonl`` is never touched and the
autouse ``_guard_no_runtime_leaks`` fixture stays satisfied.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.maintenance.task_log as tl


@pytest.fixture(autouse=True)
def _private_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Route every write in this module to a private temp file."""
    target = tmp_path / "task_log.jsonl"
    monkeypatch.setenv("NEXUS_TASK_LOG", str(target))
    return target


# ─── record + aggregate ─────────────────────────────────────────────────────
def test_record_appends_entries_and_aggregate_counts_them() -> None:
    for index in range(10):
        entry = tl.record(priority="LOW", agent_id=f"a{index}")
        assert set(entry) == set(tl.ENTRY_FIELDS)

    report = tl.aggregate()
    assert report["all_time"]["total_tasks"] == 10
    assert report["all_time"]["by_priority"][tl.LOW] == 10
    assert report["all_time"]["by_priority"][tl.MED] == 0
    assert report["all_time"]["by_priority"][tl.HIGH] == 0
    assert report["window"]["total_tasks"] == 10
    assert report["window_days"] == 7
    assert report["sampled_at"]


def test_record_normalises_priority_and_agent_id() -> None:
    tl.record(priority="  MEDium  ", agent_id="  coder  ")
    entry = tl.read_entries()[0]
    assert entry["priority"] == "medium"
    # agent_id is preserved verbatim (only priority/outcome are normalised).
    assert entry["agent_id"] == "  coder  "


def test_record_defaults_a_missing_priority_to_low() -> None:
    tl.record(priority="", agent_id="coder")
    assert tl.read_entries()[0]["priority"] == tl.LOW


def test_record_rejects_an_unknown_outcome() -> None:
    tl.record(priority="LOW", outcome="exploded")
    assert tl.read_entries()[0]["outcome"] == "generated"


def test_record_stamps_a_live_version() -> None:
    entry = tl.record(priority="LOW")
    # The version is read from the package, never hardcoded here.
    from src import __version__

    assert entry["version"] == __version__


# ─── persistence ────────────────────────────────────────────────────────────
def test_entries_persist_across_a_fresh_read() -> None:
    tl.record(priority="HIGH", agent_id="reviewer")
    # Re-read from disk through a brand-new call — no in-memory cache exists.
    entries = tl.read_entries()
    assert len(entries) == 1
    assert entries[0]["agent_id"] == "reviewer"
    assert entries[0]["priority"] == "high"


def test_malformed_lines_are_skipped() -> None:
    path = tl.log_path()
    path.write_text(
        '{"priority": "low", "outcome": "generated"}\n'
        "not json at all\n"
        "\n"
        '["also", "not", "a", "mapping"]\n'
        '{"priority": "medium", "outcome": "generated"}\n',
        encoding="utf-8",
    )
    entries = tl.read_entries()
    assert [e["priority"] for e in entries] == ["low", "medium"]


# ─── failure percentage ─────────────────────────────────────────────────────
def test_failure_pct_reflects_failed_outcomes() -> None:
    for _ in range(3):
        tl.record(priority="LOW", outcome="failed")
    tl.record(priority="LOW", outcome="generated")

    report = tl.aggregate()
    assert report["all_time"]["failed"] == 3
    assert report["all_time"]["failure_pct"] == 75.0


def test_failure_pct_is_zero_with_no_entries() -> None:
    report = tl.aggregate()
    assert report["all_time"]["total_tasks"] == 0
    assert report["all_time"]["failure_pct"] == 0.0
    assert report["is_sample_sufficient"] is False


# ─── window vs all-time ─────────────────────────────────────────────────────
def test_window_excludes_old_entries_but_all_time_keeps_them() -> None:
    path = tl.log_path()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps({"ts": old, "priority": "low", "outcome": "generated"}) + "\n"
        + json.dumps({"ts": fresh, "priority": "medium", "outcome": "generated"}) + "\n",
        encoding="utf-8",
    )
    report = tl.aggregate(window_days=7)
    assert report["window"]["total_tasks"] == 1
    assert report["window"]["by_priority"]["medium"] == 1
    assert report["all_time"]["total_tasks"] == 2


def test_naive_timestamps_are_treated_as_utc() -> None:
    path = tl.log_path()
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    path.write_text(
        json.dumps({"ts": naive, "priority": "low", "outcome": "generated"}) + "\n",
        encoding="utf-8",
    )
    assert tl.aggregate()["window"]["total_tasks"] == 1


def test_unparseable_timestamp_is_dropped_from_the_window() -> None:
    path = tl.log_path()
    path.write_text(
        json.dumps({"ts": "not-a-date", "priority": "low", "outcome": "generated"}) + "\n",
        encoding="utf-8",
    )
    report = tl.aggregate()
    assert report["window"]["total_tasks"] == 0
    assert report["all_time"]["total_tasks"] == 1


def test_window_days_falls_back_to_a_positive_int() -> None:
    assert tl.aggregate(window_days=0)["window_days"] == 7
    assert tl.aggregate(window_days=-3)["window_days"] == 7
    assert tl.aggregate(window_days="nope")["window_days"] == 7  # type: ignore[arg-type]
    assert tl.aggregate(window_days=14)["window_days"] == 14


# ─── sample sufficiency ─────────────────────────────────────────────────────
def test_sample_is_insufficient_below_the_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tl, "MIN_SAMPLE", 30)
    for _ in range(29):
        tl.record(priority="low")
    assert tl.aggregate()["is_sample_sufficient"] is False


def test_sample_becomes_sufficient_at_the_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tl, "MIN_SAMPLE", 30)
    for _ in range(30):
        tl.record(priority="low")
    report = tl.aggregate()
    assert report["is_sample_sufficient"] is True
    assert report["all_time"]["total_tasks"] == 30


def test_sample_sufficiency_uses_all_time_not_the_window(tmp_path: Path) -> None:
    """A quiet week must not read as 'insufficient' when history is long."""
    path = tl.log_path()
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    path.write_text(
        "".join(
            json.dumps({"ts": old, "priority": "low", "outcome": "generated"}) + "\n"
            for _ in range(tl.MIN_SAMPLE)
        ),
        encoding="utf-8",
    )
    report = tl.aggregate(window_days=7)
    assert report["window"]["total_tasks"] == 0
    assert report["is_sample_sufficient"] is True


# ─── rotation ───────────────────────────────────────────────────────────────
def test_rotation_moves_a_large_file_aside(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tl, "MAX_BYTES", 64)
    path = tl.log_path()
    path.write_text("x" * 200, encoding="utf-8")

    tl.record(priority="low", agent_id="coder")

    backup = path.with_name(f"{path.name}.1")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "x" * 200
    # The new entry landed in a fresh file, not appended to the huge one.
    assert tl.read_entries()[-1]["agent_id"] == "coder"


def test_rotation_shifts_older_backups_and_drops_the_oldest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tl, "MAX_BYTES", 64)
    monkeypatch.setattr(tl, "BACKUPS", 2)
    path = tl.log_path()
    path.with_name(f"{path.name}.1").write_text("oldest", encoding="utf-8")
    path.write_text("current" * 20, encoding="utf-8")

    tl.record(priority="low")

    assert path.with_name(f"{path.name}.1").read_text(encoding="utf-8") == "current" * 20
    assert path.with_name(f"{path.name}.2").read_text(encoding="utf-8") == "oldest"


def test_no_rotation_below_the_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tl, "MAX_BYTES", 10 * 1024 * 1024)
    tl.record(priority="low")
    assert not tl.log_path().with_name("task_log.jsonl.1").exists()


# ─── path resolution + isolation ────────────────────────────────────────────
def test_log_path_honours_the_environment_override(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "custom" / "ledger.jsonl"
    monkeypatch.setenv("NEXUS_TASK_LOG", str(target))
    assert tl.log_path() == target


def test_log_path_is_read_fresh_on_every_call(tmp_path: Path, monkeypatch) -> None:
    """A redirected env var between calls must be picked up (two-names trap)."""
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    monkeypatch.setenv("NEXUS_TASK_LOG", str(first))
    assert tl.log_path() == first
    monkeypatch.setenv("NEXUS_TASK_LOG", str(second))
    assert tl.log_path() == second


def test_default_path_is_the_repo_data_dir_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_TASK_LOG", raising=False)
    resolved = tl.log_path()
    assert resolved.name == "task_log.jsonl"
    # Either the repo's data/ dir (preferred) or the temp fallback — never memory/.
    assert "memory" not in resolved.parts


def test_record_never_writes_into_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("NEXUS_TASK_LOG", raising=False)
    resolved = tl.log_path()
    assert "memory" not in resolved.parts
    assert resolved.parent.name != "memory"


def test_record_survives_an_unwritable_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_TASK_LOG", "/proc/nonexistent/ledger.jsonl")
    entry = tl.record(priority="low")  # must not raise
    assert entry["priority"] == "low"


def test_read_entries_tolerates_a_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEXUS_TASK_LOG", str(tmp_path / "absent.jsonl"))
    assert tl.read_entries() == []
