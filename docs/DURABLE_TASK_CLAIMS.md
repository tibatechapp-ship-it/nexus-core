# Durable task claims and attempt history

This layer adds persistent execution ownership primitives to `OrgStore`.

## Guarantees

- A task can be claimed only while its persisted state is `pending`.
- Claiming uses a conditional SQLite update, so competing workers cannot both
  acquire the same pending task.
- Every successful claim creates a durable attempt row and records the worker,
  lease token, start time, and attempt number.
- The task stores a stable idempotency key and an immutable JSON input snapshot
  captured on its first claim.
- Completion and failure require the current lease token. A stale or foreign
  worker cannot finalize a task it no longer owns.
- Attempt history remains available after the task reaches a terminal state.

## Deliberate safety boundary

An expired lease is **not** permission to replay work. A process may have
performed an external side effect immediately before it stopped. This layer
therefore does not reclaim `running` tasks, does not reset failed tasks, and
does not retry anything automatically. Such tasks remain visible for
reconciliation and an explicit operator decision.

The idempotency key is persisted for downstream adapters to pass to external
systems. This change does not claim exactly-once delivery: an external service
must actually honor that key, and uncertain outcomes still require
reconciliation. The existing orchestrator is not switched to this API in this
change; integration must be performed separately, department by department,
after adapters accept and propagate idempotency keys.

## API

- `claim_task(task_id, worker_id, lease_seconds=300)`
- `finish_claimed_task(task_id, lease_token, result)`
- `fail_claimed_task(task_id, lease_token, error)`
- `task_attempts_for(task_id)`

Schema migration v2 is additive and preserves existing mission/task rows.


## Operator-driven reconciliation (schema v3)

Recovery inspection remains read-only. A human operator may separately call
`OrgStore.reconcile_task` with a non-empty actor, reason, and decision key.

Supported decisions:

- `manual_hold`: record a hold without changing task execution state.
- `mark_failed`: close an expired running attempt as failed, or confirm an
  already-failed task.
- `mark_completed_with_evidence`: close an expired running or failed task only
  when every supplied evidence reference belongs to the same mission and is
  marked successful.
- `retry_authorized`: preserve the original failed record and create a new
  pending task with a distinct ID and a link to the original task.

A running task cannot be reconciled by a terminal decision before its lease
expires. No reconciliation action invokes a worker or executes pending work.
Decision keys are unique per task; repeating the same decision is idempotent,
while reusing a key for a different actor/action is rejected. Every decision is
stored in `task_reconciliations` and appended to the audit log.

This is operator authorization, not exactly-once execution. The replacement
task remains pending and requires the normal orchestrator/worker claim path.


## Heartbeats and fencing generations (schema v11)

Each successful claim increments a task-local, monotonic `lease_generation`.
The generation is copied to the immutable attempt history and returned in the
claim object. Worker completion/failure should always pass that generation;
the store rejects a mismatched generation even if a caller presents a token
from an older execution.

`heartbeat_task(task_id, worker_id, lease_token, lease_generation,
lease_seconds=300)` extends only the current, unexpired lease. It performs a
conditional update under an immediate SQLite transaction, verifies worker,
random lease capability, and generation, and appends an audit event. A late
heartbeat cannot resurrect an expired lease. Expiry still does not trigger
automatic task replay or token release; operator reconciliation remains
required because external work may still be active.

Schema v11 adds the generation and heartbeat timestamps to tasks, the
generation to attempt history, and optional task/attempt ownership columns
to token reservations as groundwork for binding provider budgets to a
specific execution claim. Existing rows are migrated additively.
