"""Authorization and isolation tests for the behavior replay adapter."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.intelligence.behavior import ObservationStatus
from src.intelligence.replay import (
    BehaviorReplayError, ReplayCommandCase, execute_authorized_cases,
)


_IMAGE = "registry.example/nexus-test@sha256:" + "a" * 64


class ApprovalStore:
    def __init__(self, approval):
        self.approval = approval
        self.requested_mission = None

    def approvals_for(self, mission_id):
        self.requested_mission = mission_id
        return [self.approval] if self.approval is not None else []


def _policy(**updates):
    value = {
        "schema_version": 1,
        "execution_mode": "container",
        "container_enabled": True,
        "container_image": _IMAGE,
        "approval_id": "approval-1",
    }
    value.update(updates)
    return value


def _approval(**updates):
    value = {
        "id": "approval-1",
        "kind": "run_untrusted",
        "approved": True,
        "decided_by": "human-operator",
        "subject": _IMAGE,
    }
    value.update(updates)
    return SimpleNamespace(**value)


def _case(path: Path, case_id="case-1"):
    path.mkdir()
    return ReplayCommandCase(case_id, ("python", "-m", "pytest", "-q"), path, {"x": 1})


def test_replay_requires_persisted_matching_human_approval(tmp_path, monkeypatch) -> None:
    import src.intelligence.replay as replay
    called = False

    def fake_runner(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True, "exit_code": 0, "timeout": False,
                "truncated": False, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(replay, "run_in_container", fake_runner)
    store = ApprovalStore(_approval())
    result = execute_authorized_cases(
        mission_id="mission-1", execution_policy=_policy(),
        approval_store=store, cases=[_case(tmp_path / "case")],
    )
    assert called
    assert store.requested_mission == "mission-1"
    assert result[0].status is ObservationStatus.PASSED
    assert result[0].output_payload["runner"] == "nexus.rootless-container/v1"


@pytest.mark.parametrize("approval", [
    None,
    _approval(approved=False),
    _approval(decided_by=""),
    _approval(subject="registry.example/other@sha256:" + "b" * 64),
    _approval(kind="read_only"),
])
def test_replay_rejects_missing_or_mismatched_approval(tmp_path, monkeypatch, approval) -> None:
    import src.intelligence.replay as replay
    monkeypatch.setattr(
        replay, "run_in_container",
        lambda *args, **kwargs: pytest.fail("runner must not be called without approval"),
    )
    with pytest.raises(BehaviorReplayError):
        execute_authorized_cases(
            mission_id="mission-2", execution_policy=_policy(),
            approval_store=ApprovalStore(approval), cases=[_case(tmp_path / "case")],
        )


def test_replay_rejects_process_mode(tmp_path, monkeypatch) -> None:
    import src.intelligence.replay as replay
    monkeypatch.setattr(
        replay, "run_in_container",
        lambda *args, **kwargs: pytest.fail("host process mode must never run"),
    )
    with pytest.raises(BehaviorReplayError):
        execute_authorized_cases(
            mission_id="mission-3",
            execution_policy=_policy(execution_mode="process", trusted_local=True),
            approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
        )


def test_replay_rejects_non_digest_pinned_image(tmp_path) -> None:
    with pytest.raises(BehaviorReplayError):
        execute_authorized_cases(
            mission_id="mission-4", execution_policy=_policy(container_image="latest"),
            approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
        )


def test_replay_rejects_shared_workspace_between_cases(tmp_path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    cases = [
        ReplayCommandCase("one", ("python", "-V"), shared, {}),
        ReplayCommandCase("two", ("python", "-V"), shared, {}),
    ]
    with pytest.raises(BehaviorReplayError):
        execute_authorized_cases(
            mission_id="mission-5", execution_policy=_policy(),
            approval_store=ApprovalStore(_approval()), cases=cases,
        )


def test_replay_marks_timeout_or_truncated_output_as_failed(tmp_path, monkeypatch) -> None:
    import src.intelligence.replay as replay
    monkeypatch.setattr(
        replay, "run_in_container",
        lambda *args, **kwargs: {
            "ok": False, "exit_code": None, "timeout": True,
            "truncated": False, "stdout": "", "stderr": "timeout",
        },
    )
    result = execute_authorized_cases(
        mission_id="mission-6", execution_policy=_policy(),
        approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
    )
    assert result[0].status is ObservationStatus.FAILED
    assert result[0].output_payload["timeout"] is True


def test_replay_rejects_invalid_workspace_and_command(tmp_path) -> None:
    with pytest.raises(BehaviorReplayError):
        ReplayCommandCase("bad", (), tmp_path, {})
    with pytest.raises(BehaviorReplayError):
        ReplayCommandCase("bad", ("python", "\x00"), tmp_path, {})


def test_replay_rejects_missing_or_boolean_policy_version(tmp_path) -> None:
    with pytest.raises(BehaviorReplayError):
        execute_authorized_cases(
            mission_id="mission-7", execution_policy=_policy(schema_version=True),
            approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
        )


def test_replay_rejects_malformed_runner_result(tmp_path, monkeypatch) -> None:
    import src.intelligence.replay as replay
    monkeypatch.setattr(
        replay, "run_in_container",
        lambda *args, **kwargs: {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""},
    )
    with pytest.raises(BehaviorReplayError):
        execute_authorized_cases(
            mission_id="mission-8", execution_policy=_policy(),
            approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
        )


@pytest.mark.parametrize(
    "runner_result",
    [
        {"ok": "yes", "exit_code": 0, "timeout": False, "truncated": False, "stdout": "", "stderr": ""},
        {"ok": True, "exit_code": True, "timeout": False, "truncated": False, "stdout": "", "stderr": ""},
        {"ok": True, "exit_code": 0, "timeout": 0, "truncated": False, "stdout": "", "stderr": ""},
        {"ok": True, "exit_code": 0, "timeout": False, "truncated": "no", "stdout": "", "stderr": ""},
    ],
)
def test_replay_rejects_invalid_runner_status_types(tmp_path, monkeypatch, runner_result) -> None:
    import src.intelligence.replay as replay

    monkeypatch.setattr(replay, "run_in_container", lambda *args, **kwargs: runner_result)
    with pytest.raises(BehaviorReplayError, match="invalid status fields"):
        execute_authorized_cases(
            mission_id="mission-9", execution_policy=_policy(),
            approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
        )


@pytest.mark.parametrize("field", ["stdout", "stderr"])
def test_replay_rejects_output_over_limit(tmp_path, monkeypatch, field) -> None:
    import src.intelligence.replay as replay

    result = {
        "ok": True, "exit_code": 0, "timeout": False, "truncated": False,
        "stdout": "", "stderr": "",
    }
    result[field] = "x" * (64 * 1024 + 1)
    monkeypatch.setattr(replay, "run_in_container", lambda *args, **kwargs: result)
    with pytest.raises(BehaviorReplayError, match="bounded contract"):
        execute_authorized_cases(
            mission_id="mission-10", execution_policy=_policy(),
            approval_store=ApprovalStore(_approval()), cases=[_case(tmp_path / "case")],
        )


def test_replay_rejects_duplicate_case_ids_and_malformed_approval_store(tmp_path) -> None:
    workspace_a = tmp_path / "case-a"
    workspace_b = tmp_path / "case-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    duplicate_cases = [
        ReplayCommandCase("same", ("python", "-V"), workspace_a, {}),
        ReplayCommandCase("same", ("python", "-V"), workspace_b, {}),
    ]
    with pytest.raises(BehaviorReplayError, match="duplicate"):
        execute_authorized_cases(
            mission_id="mission-11", execution_policy=_policy(),
            approval_store=ApprovalStore(_approval()), cases=duplicate_cases,
        )

    class MalformedApprovalStore:
        def approvals_for(self, mission_id):
            return {"not": "a list"}

    with pytest.raises(BehaviorReplayError, match="malformed records"):
        execute_authorized_cases(
            mission_id="mission-12", execution_policy=_policy(),
            approval_store=MalformedApprovalStore(), cases=[_case(tmp_path / "case-c")],
        )


def test_replay_rejects_approval_store_exception_and_duplicate_approval(tmp_path) -> None:
    class RaisingApprovalStore:
        def approvals_for(self, mission_id):
            raise OSError("store unavailable")

    with pytest.raises(BehaviorReplayError, match="retrieve mission approval"):
        execute_authorized_cases(
            mission_id="mission-13", execution_policy=_policy(),
            approval_store=RaisingApprovalStore(), cases=[_case(tmp_path / "case-a")],
        )

    class DuplicateApprovalStore:
        def approvals_for(self, mission_id):
            approval = _approval()
            return [approval, approval]

    with pytest.raises(BehaviorReplayError, match="exactly one"):
        execute_authorized_cases(
            mission_id="mission-14", execution_policy=_policy(),
            approval_store=DuplicateApprovalStore(), cases=[_case(tmp_path / "case-b")],
        )
