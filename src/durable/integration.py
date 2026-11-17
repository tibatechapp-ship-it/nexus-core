"""Durable integration between the supervisor, council, and human approval gate.

The council is advisory: it can reject a request, but it can never grant
permission to execute it. Every execution requires an explicit human decision.
An interrupted process is safe to inspect and resume; an uncertain execution
is never replayed automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Protocol

from src.council.router_integration import should_use_council
from src.durable.flow import DurableFlow, FlowRejected


class SupervisorLike(Protocol):
    """The synchronous execution surface exposed by Supervisor."""

    def execute(self, prompt: str, force_strategy: str | None = None) -> dict[str, Any]:
        """Execute a prompt and return the supervisor result."""


class CouncilLike(Protocol):
    """The deliberation surface exposed by CouncilEngine."""

    def deliberate(self, question: str, context: str = "") -> Any:
        """Return a result with a verdict attribute."""


class ApprovalAuthorizer(Protocol):
    """Adapter to the application's authenticated identity/permission system."""

    def authorize(self, *, auditor: str, flow_id: str, task: str, decision: str) -> bool:
        """Return true only for an authenticated principal allowed to decide."""


@dataclass(frozen=True, slots=True)
class DurableExecutionStatus:
    """A read-only view of a durable execution."""

    flow_id: str
    stage: str | None
    waiting_for_human: bool
    council_verdict: str | None
    result: dict[str, Any] | None
    rejected: bool = False
    execution_claimed: bool = False


class DurableExecution:
    """Coordinate a supervisor run behind durable checkpoints and HITL.

    prepare() is safe to call again after a process restart: it returns the
    already persisted state instead of convening the council twice.
    approve_and_execute() records an execution-started checkpoint before
    calling the supervisor. If the process dies after that point, this class
    refuses to replay the potentially side-effecting call automatically.
    """

    def __init__(
        self,
        flow: DurableFlow,
        supervisor: SupervisorLike,
        *,
        council: CouncilLike | None = None,
        approval_authorizer: ApprovalAuthorizer | None = None,
    ) -> None:
        self.flow = flow
        self.supervisor = supervisor
        self.council = council
        self.approval_authorizer = approval_authorizer

    def prepare(self, task: str) -> DurableExecutionStatus:
        """Persist a request, consult the council when indicated, and pause."""
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")

        latest = self.flow.latest()
        if latest is not None:
            saved_task = latest["payload"].get("task")
            if saved_task != task:
                raise ValueError("flow already belongs to a different task")
            return self.status()

        council_verdict: str | None = None
        council_required = should_use_council(task)
        if council_required:
            if self.council is None:
                self.flow.checkpoint(
                    "council_unavailable",
                    {"task": task, "reason": "council_required_but_not_configured"},
                )
                return self.status()
            try:
                deliberation = self.council.deliberate(task)
                council_verdict = str(getattr(deliberation, "verdict", ""))
            except Exception as exc:
                self.flow.checkpoint(
                    "council_error",
                    {"task": task, "error": str(exc)[:500]},
                )
                return self.status()

            if council_verdict == "reject":
                self.flow.checkpoint(
                    "council_rejected",
                    {"task": task, "council_verdict": council_verdict},
                )
                return self.status()
            if council_verdict not in {"approve", "human_review"}:
                self.flow.checkpoint(
                    "council_abstained",
                    {"task": task, "council_verdict": council_verdict[:100]},
                )
                return self.status()

        self.flow.checkpoint(
            "prepared",
            {
                "task": task,
                "council_required": council_required,
                "council_verdict": council_verdict,
            },
        )
        self.flow.interrupt("تنفيذ المهمة يتطلب موافقة بشرية صريحة")
        return self.status()

    def approve_and_execute(self, *, auditor: str) -> dict[str, Any]:
        """Record human approval, then execute exactly once on the happy path."""
        latest = self.flow.latest()
        if latest is None or latest["stage"] != "prepared":
            raise ValueError("flow is not waiting at the prepared stage")

        task = str(latest["payload"]["task"])
        self._authorize(auditor=auditor, task=task, decision="approve")
        council_verdict = latest["payload"].get("council_verdict")
        if self.flow.is_interrupted:
            # Idempotent for a crash after the decision marker was written.
            self.flow.resume_after_approval("approve", auditor=auditor)
        else:
            # Recover the narrow crash window after the approved pause marker
            # was removed but before execution_started was checkpointed.
            decisions = [
                event for event in self.flow.audit.read()
                if event.get("event") == "human_decision"
                and event.get("decision") == "approve"
                and event.get("detail", {}).get("auditor") == auditor
                and event.get("detail", {}).get("reason") == "تنفيذ المهمة يتطلب موافقة بشرية صريحة"
            ]
            if not decisions:
                raise ValueError("no matching persisted human approval")

        # A filesystem-exclusive claim closes the race between concurrent
        # approvers. It is deliberately permanent: a crash after claiming but
        # before completion requires inspection, never an automatic replay.
        self._claim_execution(task=task, auditor=auditor)

        # Write-ahead marker: after this checkpoint, an automatic retry is unsafe.
        self.flow.checkpoint(
            "execution_started",
            {"task": task, "approved_by": auditor, "council_verdict": council_verdict},
        )
        try:
            result = self.supervisor.execute(task)
            if not isinstance(result, dict):
                raise TypeError("supervisor.execute must return a dictionary")
        except Exception as exc:
            failure = {"ok": False, "error": str(exc)[:1000], "task": task}
            self.flow.checkpoint("execution_failed", failure)
            return failure

        payload = {"task": task, "approved_by": auditor, "council_verdict": council_verdict, "result": result}
        self.flow.checkpoint("completed" if result.get("ok") is True else "execution_failed", payload)
        return result

    def reject(self, *, auditor: str) -> None:
        """Record a human rejection; the flow remains closed (fail-closed)."""
        latest = self.flow.latest()
        if latest is None or latest["stage"] != "prepared" or not self.flow.is_interrupted:
            raise ValueError("flow is not waiting at the prepared stage")
        task = str(latest["payload"]["task"])
        self._authorize(auditor=auditor, task=task, decision="reject")
        try:
            self.flow.resume_after_approval("reject", auditor=auditor)
        except FlowRejected:
            return

    def _claim_execution(self, *, auditor: str, task: str) -> None:
        """Atomically claim the one permitted supervisor invocation for this flow."""
        claim_path = self.flow.store / "_execution_claim.json"
        payload = json.dumps(
            {"flow_id": self.flow.flow_id, "task": task, "approved_by": auditor},
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            descriptor = os.open(
                claim_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise ValueError(
                "execution has already been claimed; manual recovery is required"
            ) from exc

        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def _authorize(self, *, auditor: str, task: str, decision: str) -> None:
        """Fail closed unless a trusted application auth adapter verifies the actor."""
        if self.approval_authorizer is None:
            raise PermissionError("an authenticated approval_authorizer is required")
        if not self.approval_authorizer.authorize(
            auditor=auditor,
            flow_id=self.flow.flow_id,
            task=task,
            decision=decision,
        ):
            raise PermissionError("human decision is not authorized")

    def status(self) -> DurableExecutionStatus:
        """Return persisted status without executing or mutating anything."""
        latest = self.flow.latest()
        payload = latest["payload"] if latest is not None else {}
        result = payload.get("result") if latest and latest["stage"] == "completed" else None
        return DurableExecutionStatus(
            flow_id=self.flow.flow_id,
            stage=latest["stage"] if latest else None,
            waiting_for_human=self.flow.is_interrupted and not self.flow.is_rejected,
            council_verdict=payload.get("council_verdict"),
            result=result if isinstance(result, dict) else None,
            rejected=self.flow.is_rejected,
            execution_claimed=(self.flow.store / "_execution_claim.json").exists(),
        )


__all__ = ["DurableExecution", "DurableExecutionStatus", "SupervisorLike", "CouncilLike", "ApprovalAuthorizer"]
