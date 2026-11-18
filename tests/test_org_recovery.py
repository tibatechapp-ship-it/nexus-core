"""Tests for conservative, read-only mission recovery and resume preflight."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.org.contracts import Mission, TaskSpec
from src.org.recovery import assess_mission_resume, inspect_mission_recovery
from src.org.store import OrgError, OrgStore


def test_running_task_requires_manual_review_after_store_reopen(tmp_path: Path) -> None:
    db = tmp_path / "org.sqlite3"
    first = OrgStore(db)
    mission = first.create_mission(Mission(title="recover", objective="inspect", status="running"))
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


def test_resume_preflight_accepts_consistent_pending_graph_without_mutation() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(
        title="resume", objective="continue", phase="A_REQUIREMENTS",
        status="running"
    ))
    first = store.add_task(TaskSpec(
        mission_id=mission.id, dept="executive", kind="requirements",
        description="requirements"
    ))
    second = store.add_task(TaskSpec(
        mission_id=mission.id, dept="repo_intel", kind="analyze",
        description="repository analysis", deps=[first.id]
    ))
    before = store.tail_audit(20)
    assessment = assess_mission_resume(store, mission.id)
    after = store.tail_audit(20)

    assert assessment.ready_for_explicit_resume is True
    assert assessment.pending_task_ids == tuple(sorted((first.id, second.id)))
    assert assessment.completed_task_ids == ()
    assert assessment.context_reconstruction_required is True
    assert assessment.execution_started is False
    assert assessment.automatic_execution_permitted is False
    assert before == after
    assert store.task_get(first.id)["state"] == "pending"


def test_resume_preflight_rejects_uncertain_running_task() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(
        title="uncertain", objective="inspect", status="running"
    ))
    task = store.add_task(TaskSpec(
        mission_id=mission.id, dept="executive", kind="requirements",
        description="possibly side-effecting"
    ))
    store.task_set_state(task.id, "running", attempts=1)

    assessment = assess_mission_resume(store, mission.id)
    assert assessment.ready_for_explicit_resume is False
    assert task.id in assessment.blocked_task_ids
    assert any("uncertain prior side effects" in reason
               for reason in assessment.blocking_reasons)


def test_resume_preflight_rejects_dependency_cycles() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(
        title="cycle", objective="reject cycle", status="running"
    ))
    first = store.add_task(TaskSpec(
        mission_id=mission.id, dept="executive", kind="requirements",
        description="first"
    ))
    second = store.add_task(TaskSpec(
        mission_id=mission.id, dept="repo_intel", kind="analyze",
        description="second", deps=[first.id]
    ))
    # Corrupt the persisted graph deliberately to exercise fail-closed preflight.
    with store._conn:
        store._conn.execute(
            "UPDATE tasks SET deps = ? WHERE id = ?",
            ('["' + second.id + '"]', first.id),
        )

    assessment = assess_mission_resume(store, mission.id)
    assert assessment.ready_for_explicit_resume is False
    assert any("dependency cycle" in issue
               for issue in assessment.dependency_violations)


def test_resume_preflight_rejects_phase_state_mismatch() -> None:
    store = OrgStore(":memory:")
    mission = store.create_mission(Mission(
        title="phase mismatch", objective="fail closed",
        phase="B_INTEL", status="running"
    ))
    store.add_task(TaskSpec(
        mission_id=mission.id, dept="executive", kind="requirements",
        description="requirements"
    ))
    assessment = assess_mission_resume(store, mission.id)
    assert assessment.ready_for_explicit_resume is False
    assert any("prior-phase task" in reason
               for reason in assessment.blocking_reasons)
