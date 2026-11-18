# Orchestrator durable-claim integration

## Scope

The executive orchestrator now acquires a durable task claim before invoking a
department executor. A task that is not pending cannot be started by this path.
Successful execution is finalized with the claim's lease token; exceptions are
recorded as failed attempts using that same token.

The wave runner only dispatches tasks whose persisted state is `pending`.
This prevents an already completed task from being invoked again when a wave is
visited more than once.

## Review-driven development revisions

A rejected code review no longer requires changing a completed development
task back to `pending`. The orchestrator creates a new deterministic task row
for the next development pass. Its parameters include the revision number and
the `supersedes_task_id` of the previous development task. The new task is
linked by a dependency on the previous task and receives its own durable claim
and attempt history.

This preserves the original execution record and makes each review-driven
development pass independently inspectable.

## Recovery and delivery guarantees

- An expired lease does not authorize automatic reclamation of a `running`
  task. Recovery remains an explicit operator decision.
- Failed tasks are not automatically retried. A deliberate new revision is a
  new task record, not a reset of the failed task.
- The idempotency key is persisted by the claim store, but this integration does
  not yet pass it to external side-effecting providers. Therefore it does not
  claim exactly-once execution for external systems.
- Every code-review round is a separate task record with its own durable
  claim and attempt history. A later review task depends on the development
  revision it evaluates; rejected review tasks remain completed records with a
  `request_changes` verdict and are never reopened.
- Verification is claimed and finalized with its lease token. A rejected
  verification report is a completed gate execution whose result records the
  rejection; an exception is recorded as a failed attempt.
- A running gate with an expired lease is not reclaimed automatically. An
  operator must inspect and reconcile the uncertain execution before creating
  any deliberate follow-up task.
- The idempotency key is persisted by the claim store, but this integration does
  not yet pass it to external side-effecting providers. Therefore it does not
  claim exactly-once execution for external systems.
- Human approval remains mandatory for release/merge; durable gate claims do
  not authorize a release or merge on their own.

## Validation

The orchestrator revision-loop test checks that a rejected review creates a
second development task, both tasks retain their own completed attempt record,
and the audit trail links the new task to the task it supersedes.

## Review and verification gate validation

The orchestrator tests assert that a successful mission leaves both the review
and verification task with one completed durable attempt. The revision-loop
test forces repeated review rejection and verifies that each development
revision has a distinct review task, with the second review linked to the
second development task. No completed review task is reset or reused.
