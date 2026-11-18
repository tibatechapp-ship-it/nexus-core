# Mission recovery and resume preflight

## Read-only recovery inventory

`inspect_mission_recovery(store, mission_id)` classifies persisted task and
mission state without changing the audit log, task state, or mission phase.
Running work is uncertain because a process may have stopped after an external
side effect. Failed and skipped work also requires explicit operator handling.

## Structural resume preflight

`assess_mission_resume(store, mission_id)` performs a read-only check before a
future continuation workflow is allowed to reconstruct runtime context. It
checks:

- the mission is still `running` and its phase is supported;
- no task is left `running`, `failed`, or `skipped`;
- tasks from earlier phases are complete and tasks from later phases remain
  pending;
- every dependency exists inside the same mission and does not depend on
  blocked work;
- the persisted dependency graph is acyclic.

The result is a structural preflight only. A positive result is **not** an
execution authorization and does not mean that the original worktree or
in-memory `MissionContext` has been restored. A continuation caller must
reconstruct and validate those artifacts against the current repository
snapshot before explicitly dispatching any work.

## Safety boundaries

- This module never claims tasks, changes mission status, updates phases, or
  writes audit events.
- Running tasks remain blocked for operator investigation; expired leases are
  not reclaimed.
- Failed and skipped tasks remain blocked until a separate explicit operator
  decision creates a safe continuation path.
- No task is automatically retried or dispatched by resume preflight.
- External side effects are not claimed to be exactly-once.
- Release/merge still requires human approval.

## Validation

Tests cover read-only behavior, a valid pending DAG, uncertain running work,
dependency cycles, and phase/task-state mismatch.
