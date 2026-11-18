"""Tests for conservative, read-only mission recovery inspection."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.org.contracts import Mission, TaskSpec
from src.org.recovery import inspect_mission_recovery
from src.org.store import OrgError, OrgStore


def test_running_task_requires_manual_review_after_store_reopen(tmp_path: Path) -> None:
    db = tmp_path / "org.sqlite3"
    first = OrgStore(db)
    mission = first.create_mission(Mission(title="recover", objective="inspect"))
    task = first.add_task(TaskSpec(
        mission_id=mission.id, dept="qa", kind="test", description="run tests"
    ))
    first.task_set_state(task.id, "running", attempts=1)
    reopened = OrgStore(db)
    before = reopened.tail_audit(20)
    report = inspect_mission_recovery(reopened, mission.id)
    after = reopened.tail_audit(20)
    assert report.disposition == "manual_intervention"
    assert report.running_task_ids == (task.id,)
    assert report.requires_human_review is True
    assert report.automatic_retry_permitted is False
    assert before == after


def test_failed_tasks_require_explicit_retry_decision() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(title="failed", objective="review"))
    task = store.add_task(TaskSpec(
        mission_id=mission.id, dept="qa", kind="test", description="test suite"
    ))
    store.task_set_state(task.id, "failed", error="runner exited", attempts=1)
    report = inspect_mission_recovery(store, mission.id)
    assert report.disposition == "retry_decision_required"
    assert report.failed_task_ids == (task.id,)
    assert report.blocked_task_ids == (task.id,)
    assert report.automatic_retry_permitted is False


def test_pending_tasks_are_reported_without_execution() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(title="pending", objective="queue"))
    task = store.add_task(TaskSpec(
        mission_id=mission.id, dept="qa", kind="test", description="queued"
    ))
    report = inspect_mission_recovery(store, mission.id)
    assert report.disposition == "pending_work"
    assert report.pending_task_ids == (task.id,)
    assert report.completed_task_ids == ()


def test_release_phase_is_not_terminal_while_mission_is_running() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(
        title="releasing", objective="prepare release", phase="G_RELEASE",
        status="running"
    ))
    report = inspect_mission_recovery(store, mission.id)
    assert report.terminal is False
    assert report.disposition == "quiescent"


def test_terminal_mission_is_never_reported_as_resumable() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(
        title="finished", objective="done", status="done", phase="G_RELEASE"
    ))
    report = inspect_mission_recovery(store, mission.id)
    assert report.terminal is True
    assert report.disposition == "terminal"
    assert report.automatic_retry_permitted is False


def test_unknown_mission_is_rejected() -> None:
    with pytest.raises(OrgError, match="مهمة غير موجودة"):
        inspect_mission_recovery(OrgStore(":memory:"), "missing")
