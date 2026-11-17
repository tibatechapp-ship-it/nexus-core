"""Integration tests for durable supervisor/council/human orchestration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from pathlib import Path
from typing import Any

import pytest

from src.durable import ApprovalAuthorizer, DurableExecution as PublicDurableExecution, DurableFlow
from src.durable.integration import DurableExecution
from src.durable.snapshots import SnapshotError


@dataclass
class _CouncilResult:
    verdict: str


class _Council:
    def __init__(self, verdict: str = "approve") -> None:
        self.verdict = verdict
        self.calls = 0

    def deliberate(self, question: str, context: str = "") -> _CouncilResult:
        self.calls += 1
        return _CouncilResult(self.verdict)


class _AllowApproval:
    def authorize(self, *, auditor: str, flow_id: str, task: str, decision: str) -> bool:
        return bool(auditor and flow_id and task and decision in {"approve", "reject"})


class _Supervisor:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {"ok": True, "results": [{"agent": "coder", "ok": True}]}
        self.calls: list[str] = []

    def execute(self, prompt: str, force_strategy: str | None = None) -> dict[str, Any]:
        self.calls.append(prompt)
        return self.result


def _flow(tmp_path: Path, flow_id: str = "task-1") -> DurableFlow:
    return DurableFlow(flow_id, store_dir=tmp_path)


def test_low_risk_request_waits_for_explicit_human_approval(tmp_path: Path) -> None:
    supervisor = _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=_AllowApproval())
    status = execution.prepare("summarize the README")

    assert status.stage == "prepared"
    assert status.waiting_for_human is True
    assert supervisor.calls == []

    result = execution.approve_and_execute(auditor="release-manager")
    assert result["ok"] is True
    assert supervisor.calls == ["summarize the README"]
    assert execution.status().stage == "completed"


def test_high_risk_request_requires_council_and_human_approval(tmp_path: Path) -> None:
    council, supervisor = _Council("approve"), _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, council=council, approval_authorizer=_AllowApproval())

    status = execution.prepare("deploy security changes to production")
    assert council.calls == 1
    assert status.council_verdict == "approve"
    assert status.waiting_for_human is True
    assert supervisor.calls == []

    execution.approve_and_execute(auditor="security-owner")
    assert supervisor.calls == ["deploy security changes to production"]


def test_council_rejection_never_executes(tmp_path: Path) -> None:
    council, supervisor = _Council("reject"), _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, council=council, approval_authorizer=_AllowApproval())

    status = execution.prepare("deploy security changes to production")
    assert status.stage == "council_rejected"
    assert status.waiting_for_human is False
    assert supervisor.calls == []
    with pytest.raises(ValueError, match="prepared"):
        execution.approve_and_execute(auditor="operator")


def test_council_unavailable_fails_closed_for_high_risk(tmp_path: Path) -> None:
    execution = DurableExecution(_flow(tmp_path), _Supervisor(), approval_authorizer=_AllowApproval())
    status = execution.prepare("deploy security changes to production")
    assert status.stage == "council_unavailable"
    assert not status.waiting_for_human


def test_council_exception_fails_closed(tmp_path: Path) -> None:
    class BrokenCouncil:
        def deliberate(self, question: str, context: str = "") -> Any:
            raise RuntimeError("offline")

    execution = DurableExecution(_flow(tmp_path), _Supervisor(), council=BrokenCouncil(), approval_authorizer=_AllowApproval())
    assert execution.prepare("deploy security changes to production").stage == "council_error"


def test_restart_does_not_repeat_council_or_lose_pending_approval(tmp_path: Path) -> None:
    council, supervisor = _Council(), _Supervisor()
    first = DurableExecution(_flow(tmp_path), supervisor, council=council, approval_authorizer=_AllowApproval())
    first.prepare("deploy security changes to production")

    restarted = DurableExecution(_flow(tmp_path), supervisor, council=council, approval_authorizer=_AllowApproval())
    status = restarted.prepare("deploy security changes to production")
    assert status.waiting_for_human is True
    assert council.calls == 1
    assert supervisor.calls == []


def test_human_rejection_is_audited_and_never_executes(tmp_path: Path) -> None:
    supervisor = _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=_AllowApproval())
    execution.prepare("summarize the README")

    execution.reject(auditor="human-reviewer")
    assert supervisor.calls == []
    rejected_status = execution.status()
    assert rejected_status.rejected is True
    assert rejected_status.waiting_for_human is False
    audit = _flow(tmp_path).audit.read()
    assert any(row.get("decision") == "reject" for row in audit)
    with pytest.raises(ValueError, match="مسبقًا"):
        _flow(tmp_path).resume_after_approval("approve", auditor="another-reviewer")


def test_execution_failure_is_persisted_and_not_replayed(tmp_path: Path) -> None:
    class BrokenSupervisor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, prompt: str, force_strategy: str | None = None) -> dict[str, Any]:
            self.calls += 1
            raise RuntimeError("worker crashed")

    supervisor = BrokenSupervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=_AllowApproval())
    execution.prepare("summarize the README")
    result = execution.approve_and_execute(auditor="operator")
    assert result["ok"] is False
    assert execution.status().stage == "execution_failed"
    with pytest.raises(ValueError, match="prepared"):
        execution.approve_and_execute(auditor="operator")
    assert supervisor.calls == 1


def test_crash_after_write_ahead_checkpoint_requires_manual_recovery(tmp_path: Path) -> None:
    class CrashSupervisor:
        def execute(self, prompt: str, force_strategy: str | None = None) -> dict[str, Any]:
            raise KeyboardInterrupt()

    execution = DurableExecution(_flow(tmp_path), CrashSupervisor(), approval_authorizer=_AllowApproval())
    execution.prepare("summarize the README")
    with pytest.raises(KeyboardInterrupt):
        execution.approve_and_execute(auditor="operator")

    restarted = DurableExecution(_flow(tmp_path), _Supervisor(), approval_authorizer=_AllowApproval())
    assert restarted.status().stage == "execution_started"
    with pytest.raises(ValueError, match="prepared"):
        restarted.approve_and_execute(auditor="operator")



def test_crash_after_approval_marker_removal_recovers_from_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    supervisor = _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=_AllowApproval())
    execution.prepare("summarize the README")

    original_unlink = Path.unlink

    def unlink_then_crash(path: Path, *args: Any, **kwargs: Any) -> None:
        original_unlink(path, *args, **kwargs)
        if path.name == "_paused.json":
            raise OSError("simulated process interruption after approval persistence")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", unlink_then_crash)
        with pytest.raises(OSError, match="simulated process interruption"):
            execution.approve_and_execute(auditor="operator")

    restarted = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=_AllowApproval())
    result = restarted.approve_and_execute(auditor="operator")
    assert result["ok"] is True
    assert supervisor.calls == ["summarize the README"]
    assert restarted.status().stage == "completed"


def test_approval_marker_write_is_idempotent_for_same_auditor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flow = _flow(tmp_path)
    flow.checkpoint("prepared", {"task": "summarize the README"})
    flow.interrupt("human approval required")

    original_append = flow.audit.append

    def append_then_crash(event: str, **kwargs: Any) -> dict[str, Any]:
        if event == "human_decision":
            raise OSError("simulated interruption after decision marker persistence")
        return original_append(event, **kwargs)

    monkeypatch.setattr(flow.audit, "append", append_then_crash)
    with pytest.raises(OSError, match="decision marker persistence"):
        flow.resume_after_approval("approve", auditor="operator")

    monkeypatch.setattr(flow.audit, "append", original_append)
    flow.resume_after_approval("approve", auditor="operator")
    assert flow.is_interrupted is False
    events = flow.audit.read()
    assert sum(row.get("event") == "human_decision" for row in events) == 1
    assert sum(row.get("event") == "resume" for row in events) == 1

def test_missing_authorizer_fails_closed(tmp_path: Path) -> None:
    supervisor = _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor)
    execution.prepare("summarize the README")
    with pytest.raises(PermissionError, match="authenticated approval_authorizer"):
        execution.approve_and_execute(auditor="forged-operator")
    assert supervisor.calls == []


def test_invalid_task_is_rejected_without_writing_state(tmp_path: Path) -> None:
    execution = DurableExecution(_flow(tmp_path), _Supervisor(), approval_authorizer=_AllowApproval())
    with pytest.raises(ValueError, match="non-empty"):
        execution.prepare("   ")
    assert execution.status().stage is None


def test_public_package_exports_orchestration_contract() -> None:
    approval: ApprovalAuthorizer = _AllowApproval()
    assert PublicDurableExecution is DurableExecution
    assert callable(approval.authorize)


def test_denied_authorizer_never_executes(tmp_path: Path) -> None:
    class DenyApproval:
        def authorize(self, *, auditor: str, flow_id: str, task: str, decision: str) -> bool:
            return False

    supervisor = _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=DenyApproval())
    execution.prepare("summarize the README")
    with pytest.raises(PermissionError, match="not authorized"):
        execution.approve_and_execute(auditor="untrusted-user")
    assert supervisor.calls == []
    assert execution.status().stage == "prepared"


def test_council_human_review_still_requires_human_approval(tmp_path: Path) -> None:
    council, supervisor = _Council("human_review"), _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, council=council, approval_authorizer=_AllowApproval())

    status = execution.prepare("deploy security changes to production")
    assert status.stage == "prepared"
    assert status.council_verdict == "human_review"
    assert supervisor.calls == []

    execution.approve_and_execute(auditor="security-owner")
    assert supervisor.calls == ["deploy security changes to production"]


def test_council_abstention_fails_closed(tmp_path: Path) -> None:
    council, supervisor = _Council("abstain"), _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, council=council, approval_authorizer=_AllowApproval())

    status = execution.prepare("deploy security changes to production")
    assert status.stage == "council_abstained"
    assert not status.waiting_for_human
    assert supervisor.calls == []



def test_concurrent_approvals_claim_supervisor_execution_exactly_once(tmp_path: Path) -> None:
    barrier = Barrier(2)

    class ConcurrentAuthorizer:
        def authorize(self, *, auditor: str, flow_id: str, task: str, decision: str) -> bool:
            barrier.wait(timeout=5)
            return True

    supervisor = _Supervisor()
    flow = _flow(tmp_path)
    execution = DurableExecution(
        flow,
        supervisor,
        approval_authorizer=ConcurrentAuthorizer(),
    )
    execution.prepare("summarize the README")

    def approve() -> str:
        try:
            execution.approve_and_execute(auditor="release-manager")
            return "executed"
        except (ValueError, FileNotFoundError):
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: approve(), range(2)))

    assert outcomes.count("executed") == 1
    assert supervisor.calls == ["summarize the README"]
    assert execution.status().execution_claimed is True


def test_crash_after_execution_claim_is_never_replayed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    supervisor = _Supervisor()
    flow = _flow(tmp_path)
    execution = DurableExecution(flow, supervisor, approval_authorizer=_AllowApproval())
    execution.prepare("summarize the README")

    original_checkpoint = flow.checkpoint

    def crash_before_execution_started(stage: str, state: dict[str, Any]) -> Path:
        if stage == "execution_started":
            raise OSError("simulated crash after exclusive execution claim")
        return original_checkpoint(stage, state)

    monkeypatch.setattr(flow, "checkpoint", crash_before_execution_started)
    with pytest.raises(OSError, match="exclusive execution claim"):
        execution.approve_and_execute(auditor="operator")

    restarted = DurableExecution(_flow(tmp_path), supervisor, approval_authorizer=_AllowApproval())
    assert restarted.status().stage == "prepared"
    assert restarted.status().execution_claimed is True
    assert supervisor.calls == []
    with pytest.raises(ValueError, match="already been claimed"):
        restarted.approve_and_execute(auditor="operator")
    assert supervisor.calls == []


def _tampered_prepared_execution(tmp_path: Path) -> tuple[DurableFlow, _Supervisor, DurableExecution]:
    flow = _flow(tmp_path, "tampered-chain")
    flow.checkpoint("history", {"safe": True})
    flow.checkpoint("prepared", {"task": "summarize the README", "council_verdict": None})
    flow.interrupt("human approval required")
    first = next(flow.store.glob("0001-*.json"))
    import json

    snapshot = json.loads(first.read_text(encoding="utf-8"))
    snapshot["snapshot"]["payload"]["safe"] = False
    first.write_text(json.dumps(snapshot), encoding="utf-8")
    supervisor = _Supervisor()
    execution = DurableExecution(flow, supervisor, approval_authorizer=_AllowApproval())
    return flow, supervisor, execution


def test_status_rejects_tampered_earlier_checkpoint(tmp_path: Path) -> None:
    _, _, execution = _tampered_prepared_execution(tmp_path)
    with pytest.raises(SnapshotError):
        execution.status()


def test_approval_rejects_tampered_earlier_checkpoint_before_execution(tmp_path: Path) -> None:
    _, supervisor, execution = _tampered_prepared_execution(tmp_path)
    with pytest.raises(SnapshotError):
        execution.approve_and_execute(auditor="release-manager")
    assert supervisor.calls == []
