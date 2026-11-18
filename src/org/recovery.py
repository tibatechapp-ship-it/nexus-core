"""Read-only recovery inventory and resume preflight for persisted missions.

Inspection never mutates state or executes work. A resume preflight only
establishes whether the persisted task graph is structurally safe to hand to
an explicit continuation caller; it does not reconstruct runtime context,
validate a worktree snapshot, or authorize execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.org.contracts import MISSION_STATUSES
from src.org.store import OrgError, OrgStore

__all__ = [
    "MissionRecoveryReport",
    "MissionResumeAssessment",
    "inspect_mission_recovery",
    "assess_mission_resume",
]

_PHASE_ORDER = {
    "A_REQUIREMENTS": 0,
    "B_INTEL": 1,
    "C_DEVELOP": 2,
    "D_REVIEW": 3,
    "E_TESTING": 4,
    "F_VERIFICATION": 5,
    "G_RELEASE": 6,
}
_DEPARTMENT_PHASE = {
    "executive": 0,
    "repo_intel": 1,
    "development": 2,
    "code_review": 3,
    "qa": 4,
    "security": 4,
    "verification": 5,
    "release": 6,
}


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


@dataclass(frozen=True)
class MissionResumeAssessment:
    """Read-only structural preflight; never an execution authorization."""

    mission_id: str
    mission_status: str
    phase: str
    ready_for_explicit_resume: bool
    pending_task_ids: tuple[str, ...]
    completed_task_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    dependency_violations: tuple[str, ...]
    context_reconstruction_required: bool = True
    execution_started: bool = False
    automatic_execution_permitted: bool = False


def inspect_mission_recovery(
    store: OrgStore, mission_id: str
) -> MissionRecoveryReport:
    """Classify persisted mission/task state without mutating or executing it."""
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


def assess_mission_resume(
    store: OrgStore, mission_id: str
) -> MissionResumeAssessment:
    """Check persisted mission graph consistency without creating runtime state.

    A positive result means only that the task graph is structurally suitable
    for an explicit continuation workflow. The caller must still rebuild and
    validate MissionContext/worktree state against the source repository before
    any task is dispatched.
    """
    mission = store.mission_get(mission_id)
    if mission is None:
        raise OrgError(f"مهمة غير موجودة: {mission_id}")

    report = inspect_mission_recovery(store, mission_id)
    rows = store.tasks_for_mission(mission_id)
    reasons: list[str] = []
    violations: list[str] = []

    if mission.status != "running":
        reasons.append(f"mission status must be running, got {mission.status}")
    if mission.phase not in _PHASE_ORDER:
        reasons.append(f"unsupported mission phase: {mission.phase}")
    if report.running_task_ids:
        reasons.append("running tasks have uncertain prior side effects")
    if report.failed_task_ids:
        reasons.append("failed tasks require explicit operator reconciliation")
    if report.skipped_task_ids:
        reasons.append("skipped tasks require operator review")
    if not rows:
        reasons.append("mission has no persisted task graph")

    by_id = {str(row.get("id", "")): row for row in rows}
    graph: dict[str, set[str]] = {}
    states = {task_id: str(row.get("state", "")) for task_id, row in by_id.items()}
    current_order = _PHASE_ORDER.get(mission.phase, -1)

    for task_id, row in by_id.items():
        dept = str(row.get("dept", ""))
        stage = _DEPARTMENT_PHASE.get(dept)
        if stage is None:
            reasons.append(f"task {task_id} has unsupported department {dept!r}")
        elif current_order >= 0:
            state = states[task_id]
            if stage < current_order and state != "done":
                reasons.append(
                    f"prior-phase task {task_id} is {state}, expected done")
            elif stage > current_order and state != "pending":
                reasons.append(
                    f"future-phase task {task_id} is {state}, expected pending")

        try:
            deps_raw = json.loads(row.get("deps") or "[]")
        except (TypeError, json.JSONDecodeError):
            violations.append(f"task {task_id} has malformed dependency JSON")
            graph[task_id] = set()
            continue
        if not isinstance(deps_raw, list) or any(
            not isinstance(dep, str) or not dep for dep in deps_raw
        ):
            violations.append(f"task {task_id} has invalid dependency entries")
            graph[task_id] = set()
            continue

        deps = set(deps_raw)
        graph[task_id] = deps
        for dependency_id in deps:
            dependency = by_id.get(dependency_id)
            if dependency is None:
                violations.append(
                    f"task {task_id} references missing or foreign dependency "
                    f"{dependency_id}")
                continue
            if states.get(dependency_id) in {"failed", "running", "skipped"}:
                violations.append(
                    f"task {task_id} depends on blocked task {dependency_id}")

    # Kahn's algorithm detects cycles without relying on persisted row order.
    remaining = {task_id: set(deps) & set(by_id) for task_id, deps in graph.items()}
    completed: set[str] = set()
    while remaining:
        ready = sorted(
            task_id for task_id, deps in remaining.items() if deps <= completed)
        if not ready:
            violations.append("persisted task graph contains a dependency cycle")
            break
        for task_id in ready:
            remaining.pop(task_id)
            completed.add(task_id)

    blocked_ids = tuple(sorted(
        set(report.running_task_ids)
        | set(report.failed_task_ids)
        | set(report.skipped_task_ids)
    ))
    pending_ids = tuple(sorted(report.pending_task_ids))
    completed_ids = tuple(sorted(report.completed_task_ids))
    reasons = list(dict.fromkeys(reasons))
    violations = list(dict.fromkeys(violations))
    ready = not reasons and not violations

    return MissionResumeAssessment(
        mission_id=mission.id,
        mission_status=mission.status,
        phase=mission.phase,
        ready_for_explicit_resume=ready,
        pending_task_ids=pending_ids,
        completed_task_ids=completed_ids,
        blocked_task_ids=blocked_ids,
        blocking_reasons=tuple(reasons),
        dependency_violations=tuple(violations),
    )
