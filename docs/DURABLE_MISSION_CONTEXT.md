# Durable mission context and repository identity

## What is checkpointed

After each successfully completed ordinary task, and after the review and
verification gates, the orchestrator appends an immutable SQLite checkpoint.
Each payload is SHA-256 checked on read, and SQLite triggers reject updates or deletions so checkpoints are append-only. Worktree copies are stored under owner-only directories with owner-only file permissions. Failed checkpoint commits remove their unreferenced worktree copy. The checkpoint contains the current persisted mission record and the
serializable MissionContext fields used by later departments, including the
repository map, affected-file map, original file contents, diffs, test/security
reports, review decision, claims, release text, and usage counters.

Each checkpoint also records a digest of the durable task ledger (task identity, inputs, states, attempts, results, and update timestamps). Restore rejects a checkpoint if task state advanced after that context was captured, closing the crash window between task completion and checkpoint persistence.

When a worktree exists, its files are copied to a mission-scoped persistent
state directory outside the source repository. Each checkpoint receives its
own immutable worktree copy and SHA-256 tree fingerprint. The live temporary
worktree remains owned by the active execution and may still be cleaned up
after terminal completion.

## Repository identity

The source repository fingerprint includes:
- a deterministic SHA-256 digest over relative file paths and file contents;
- symlink entries without following their targets;
- the resolved repository root;
- Git HEAD, current branch, and staged-index diff digest when Git metadata is available; executable mode bits are included in file entries.

Generated/cache directories and .git are excluded from the tree digest.
The first checkpoint establishes the mission's repository baseline. Later
checkpoints reject any baseline drift instead of silently accepting a changed
source tree.

## Restore boundary

`restore_mission_context` reconstructs the typed mission context and a
non-owning `Worktree` only after checking the source repository fingerprint,
the expected repository path, the persisted worktree location, and its
fingerprint. A mismatch fails closed.

`ExecutiveOrchestrator.restore_context_for_resume` additionally requires the
read-only mission task-graph preflight to pass. It records a restore audit
event, but does not claim tasks, dispatch agents, advance phases, or authorize
release/merge. A separate explicit continuation state machine is still needed
before any resumed execution is allowed.

## Storage and retention

The default state root is `~/.nexus-core/missions`; callers can inject another
persistent path. The root must be outside the source repository. Checkpoints
and their worktree copies are append-only at this stage. Retention/garbage
collection is intentionally not automatic.

## Guarantees and limitations

- Checkpoint records are append-only and payload-digest checked; each references its repository and
  worktree fingerprints.
- The system rejects source, worktree, or task-ledger drift before context restoration.
- No automatic retry, task claim, or agent execution occurs during restore.
- A tree fingerprint proves byte-level identity for the included files; it
  does not prove that external services, databases, credentials, or remote
  systems are unchanged.
- Git metadata may be absent for non-Git source directories; the content tree
  digest remains required.
- This feature does not provide exactly-once external side effects.
- Human approval remains mandatory for release/merge.

## Explicit continuation

Call `resume_mission(mission_id, actor=..., reason=..., expected_repo_root=...)` only after an
operator or supervising caller has decided to continue the mission. The actor and non-empty reason are required and recorded in the audit log. The method
performs the read-only task-graph preflight and checkpoint restoration first.
It then rebuilds task specifications from persisted rows, preserving every
task ID and dependency, and dispatches pending work from the recorded phase.
Completed tasks are not replayed. Review decisions are read from their durable
gate result; verification uses its dedicated gate and persisted result. A
running, failed, skipped, malformed, or dependency-inconsistent task blocks
continuation. This is not a lease takeover or an automatic retry mechanism.


## Exclusive mission-level resume lock

Every `resume_mission` call first acquires an atomic, durable SQLite lock for
that mission. A partial unique index permits only one `running` resume record
per mission, including across independent store connections and processes.
The lock is finished as `completed` or `failed` with its unguessable token.
A process crash intentionally leaves the record `running`; no timeout or
lease expiry silently transfers ownership.

An operator may clear an orphaned lock only through
`abandon_mission_resume(mission_id, actor=..., reason=...,
confirm_process_stopped=True)`. This action records an immutable decision
in the resume history and audit log. The confirmation must only be supplied
after independently verifying that the previous process is stopped. Abandoning
a lock does not retry or execute any task; a new explicit resume call is still
required.
