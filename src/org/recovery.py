"""Read-only recovery inventory for persisted organizational missions.

This module classifies persisted work without executing or replaying it. A task
left in running may have performed an external side effect before the process
stopped; such work must be inspected by an operator before retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.org.contracts import MISSION_STATUSES
from src.org.store import OrgError, OrgStore

__all__ = ["MissionRecoveryReport", "inspect_mission_recovery"]


@dataclass(frozen=True)
class MissionRecoveryReport:
    """Immutable snapshot of what an operator must do after interruption."""

    mission_id: str
    mission_status: str
    phase: str
    disposition: str
    task_count: int
    pending_task_ids: tuple[str, ...]
    running_task_ids: tuple[str, ...]
    failed_task_ids: tuple[str, ...]
    completed_task_ids: tuple[str, ...]
    skipped_task_ids: tuple[str, ...]
    requires_human_review: bool
    automatic_retry_permitted: bool = False

    @property
    def terminal(self) -> bool:
        return self.disposition == "terminal"

    @property
    def blocked_task_ids(self) -> tuple[str, ...]:
        """Tasks whose prior attempt cannot be safely replayed automatically."""
        return self.running_task_ids + self.failed_task_ids


def inspect_mission_recovery(
    store: OrgStore, mission_id: str
) -> MissionRecoveryReport:
    """Classify persisted mission/task state without mutating or executing it.

    Precedence is conservative: terminal missions are terminal; otherwise any
    running task requires manual inspection, then failed tasks require an
    explicit retry decision, and only then are pending tasks reported.
    """
    mission = store.mission_get(mission_id)
    if mission is None:
        raise OrgError(f"مهمة غير موجودة: {mission_id}")

    if mission.status not in MISSION_STATUSES:
        raise OrgError(f"حالة مهمة غير معروفة: {mission.status}")
    rows: list[dict[str, Any]] = store.tasks_for_mission(mission_id)
    states: dict[str, list[str]] = {
        "pending": [], "running": [], "failed": [], "done": [], "skipped": []
    }
    for row in rows:
        task_id = str(row.get("id", ""))
        state = str(row.get("state", ""))
        if state not in states:
            raise OrgError(f"حالة مهمة فرعية غير معروفة في السجل: {state!r}")
        states[state].append(task_id)

    terminal = mission.status in {"done", "failed", "cancelled"}
    if terminal:
        disposition = "terminal"
    elif states["running"]:
        disposition = "manual_intervention"
    elif states["failed"]:
        disposition = "retry_decision_required"
    elif states["pending"]:
        disposition = "pending_work"
    else:
        disposition = "quiescent"

    return MissionRecoveryReport(
        mission_id=mission.id, mission_status=mission.status, phase=mission.phase,
        disposition=disposition, task_count=len(rows),
        pending_task_ids=tuple(sorted(states["pending"])),
        running_task_ids=tuple(sorted(states["running"])),
        failed_task_ids=tuple(sorted(states["failed"])),
        completed_task_ids=tuple(sorted(states["done"])),
        skipped_task_ids=tuple(sorted(states["skipped"])),
        requires_human_review=disposition in {
            "manual_intervention", "retry_decision_required"
        },
        automatic_retry_permitted=False,
    )
