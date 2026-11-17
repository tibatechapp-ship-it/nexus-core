# Durable Supervisor + Council Integration

This vertical slice connects the existing synchronous Supervisor.execute
contract, the CouncilEngine.deliberate contract, and DurableFlow.

## Safety contract

1. High-risk or decision-sensitive prompts are sent to the council using
   should_use_council.
2. A council rejection, abstention, exception, or missing council fails closed.
   A council approval is advisory and never substitutes for human approval.
3. No supervisor execution occurs before an explicit human approval recorded
   by DurableFlow.
4. A write-ahead execution_started checkpoint is persisted before calling
   the supervisor. If the process dies during that call, the run is not replayed
   automatically because the external side effect may already have happened.
   An exclusive, fsynced per-flow execution claim is created immediately before
   that checkpoint. Concurrent approval requests cannot both acquire it. If a
   crash occurs after claiming but before completion, the claim remains and
   requires manual inspection; it is never silently cleared or replayed.
5. Human decisions and state transitions are retained in the append-only audit
   log and signed checkpoint chain.
6. Interrupt creation uses write-ahead audit: the uniquely identified interrupt
   event is fsynced before the pause marker is published. If the process dies
   between those writes, reconstructing DurableFlow restores the missing marker
   from the unresolved audit event. Human decisions reference the same
   interruption_id so recovery cannot confuse separate pauses with equal reasons.

## Usage

    from pathlib import Path
    from src.council import CouncilEngine
    from src.durable import DurableFlow
    from src.durable.integration import DurableExecution
    from src.orchestrator.supervisor import Supervisor

    flow = DurableFlow("change-2026-001", store_dir=Path(".nexus/runs"))
    # يوفّر التطبيق هذا المحوّل ويربطه بجلسة المستخدم وصلاحياته الفعلية.
    # لا تقبل قيمة auditor وحدها كإثبات هوية.
    from my_application.auth import approval_authorizer

    runner = DurableExecution(
        flow,
        Supervisor(use_rag=False, verbose=False),
        council=CouncilEngine(),
        approval_authorizer=approval_authorizer,
    )

    status = runner.prepare("Review and deploy the production security patch")
    if status.waiting_for_human:
        # Present flow_id, task, council verdict, and audit evidence to an operator.
        # Continue only after an authenticated human decision:
        result = runner.approve_and_execute(auditor="operator-id")

After a process restart, reconstruct the same DurableFlow and
DurableExecution with the same flow_id. Calling prepare with the same task
returns the persisted state and does not call the council again.

## Interrupt recovery

The audit event is the durable source of truth for a newly requested pause. On
flow reconstruction, an unresolved interrupt event without a pause marker is
replayed into an atomic marker write. This closes the crash window between audit
append and marker publication. Decision, resume, and closure events carry the
same interruption_id, preventing an older decision from resolving a newer pause.


## Recovery boundary

If the latest stage is execution_started, inspect the supervisor's external
systems before taking any action. The integration deliberately does not retry
that call; the existing supervisor has no idempotency-key contract, so automatic
replay could duplicate side effects. A future version may add idempotency keys
end-to-end before enabling safe retry.


## Authentication boundary

The adapter requires an `ApprovalAuthorizer` backed by the application's
authenticated identity/session and permission policy. Without this adapter,
approval and rejection are denied. The durable layer records the verified
principal identifier supplied by the adapter; it does not authenticate users
or grant permissions itself. The `my_application.auth` import above is an
application-owned integration point, not a module shipped by this repository.


## Single-execution claim and recovery

The durable adapter creates `_execution_claim.json` with exclusive file creation
(`O_CREAT | O_EXCL`) and fsyncs the claim before writing the
`execution_started` checkpoint or invoking the supervisor. This is the
per-flow concurrency gate: only one caller can win, even when two authenticated
approvals arrive concurrently.

The claim is intentionally permanent. If the process stops after the claim is
written but before the execution checkpoint, inspect the audit log, claim file,
and external systems before deciding how to proceed. The library does not
provide a force-clear or automatic retry path because it cannot prove that an
external side effect did not occur. `DurableExecutionStatus.execution_claimed`
exposes this state to operators.
