# Mission Recovery Inventory

`src.org.recovery.inspect_mission_recovery` provides a read-only recovery view
for a persisted organizational mission.

## Dispositions

| Disposition | Meaning | Operator action |
|---|---|---|
| `terminal` | Mission is done, failed, or cancelled | Review its final report; do not replay it |
| `manual_intervention` | At least one task was left in `running` | Inspect logs and external systems before any retry |
| `retry_decision_required` | One or more tasks failed | Decide explicitly whether a new attempt is safe |
| `pending_work` | Work remains pending and no task is running or failed | Hand pending work to a separately authorized scheduler |
| `quiescent` | No pending, running, or failed tasks remain | Inspect mission-level state and evidence |

## Safety boundary

Inspection does not mutate mission state, append audit records, invoke agents,
or execute repository code. It never retries tasks. A task persisted as
`running` is treated as an uncertain side effect: the process may have stopped
after an external operation began but before its result was committed.

This is a recovery inventory, not an automatic resume engine. Safe automatic
resume requires durable task inputs, idempotency keys propagated to every
external side effect, and an atomic claim/lease protocol. Until those contracts
exist end-to-end, the report always sets `automatic_retry_permitted` to false.
