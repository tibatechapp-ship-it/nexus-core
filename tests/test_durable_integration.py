"""Integration tests for durable supervisor/council/human orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.durable import DurableFlow
from src.durable.integration import DurableExecution


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
    execution = DurableExecution(_flow(tmp_path), supervisor)
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
    execution = DurableExecution(_flow(tmp_path), supervisor, council=council)

    status = execution.prepare("deploy security changes to production")
    assert council.calls == 1
    assert status.council_verdict == "approve"
    assert status.waiting_for_human is True
    assert supervisor.calls == []

    execution.approve_and_execute(auditor="security-owner")
    assert supervisor.calls == ["deploy security changes to production"]


def test_council_rejection_never_executes(tmp_path: Path) -> None:
    council, supervisor = _Council("reject"), _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor, council=council)

    status = execution.prepare("deploy security changes to production")
    assert status.stage == "council_rejected"
    assert status.waiting_for_human is False
    assert supervisor.calls == []
    with pytest.raises(ValueError, match="prepared"):
        execution.approve_and_execute(auditor="operator")


def test_council_unavailable_fails_closed_for_high_risk(tmp_path: Path) -> None:
    execution = DurableExecution(_flow(tmp_path), _Supervisor())
    status = execution.prepare("deploy security changes to production")
    assert status.stage == "council_unavailable"
    assert not status.waiting_for_human


def test_council_exception_fails_closed(tmp_path: Path) -> None:
    class BrokenCouncil:
        def deliberate(self, question: str, context: str = "") -> Any:
            raise RuntimeError("offline")

    execution = DurableExecution(_flow(tmp_path), _Supervisor(), council=BrokenCouncil())
    assert execution.prepare("deploy security changes to production").stage == "council_error"


def test_restart_does_not_repeat_council_or_lose_pending_approval(tmp_path: Path) -> None:
    council, supervisor = _Council(), _Supervisor()
    first = DurableExecution(_flow(tmp_path), supervisor, council=council)
    first.prepare("deploy security changes to production")

    restarted = DurableExecution(_flow(tmp_path), supervisor, council=council)
    status = restarted.prepare("deploy security changes to production")
    assert status.waiting_for_human is True
    assert council.calls == 1
    assert supervisor.calls == []


def test_human_rejection_is_audited_and_never_executes(tmp_path: Path) -> None:
    supervisor = _Supervisor()
    execution = DurableExecution(_flow(tmp_path), supervisor)
    execution.prepare("summarize the README")

    execution.reject(auditor="human-reviewer")
    assert supervisor.calls == []
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
    execution = DurableExecution(_flow(tmp_path), supervisor)
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

    execution = DurableExecution(_flow(tmp_path), CrashSupervisor())
    execution.prepare("summarize the README")
    with pytest.raises(KeyboardInterrupt):
        execution.approve_and_execute(auditor="operator")

    restarted = DurableExecution(_flow(tmp_path), _Supervisor())
    assert restarted.status().stage == "execution_started"
    with pytest.raises(ValueError, match="prepared"):
        restarted.approve_and_execute(auditor="operator")


def test_invalid_task_is_rejected_without_writing_state(tmp_path: Path) -> None:
    execution = DurableExecution(_flow(tmp_path), _Supervisor())
    with pytest.raises(ValueError, match="non-empty"):
        execution.prepare("   ")
    assert execution.status().stage is None
