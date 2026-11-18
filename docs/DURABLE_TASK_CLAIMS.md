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
