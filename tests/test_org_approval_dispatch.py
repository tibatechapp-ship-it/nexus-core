"""Integration tests for atomic one-time approval and effect dispatch."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from src.org.contracts import Mission, TaskSpec
from src.org.effect_approvals import EffectApprovalError, EffectApprovalService
from src.org.external_effects import EffectCapability, EffectNotAuthorized, EffectUncertain, ExternalEffectDispatcher
from src.org.store import OrgStore


class Adapter:
    provider_id = "scm-test"
    capabilities = {"comment": EffectCapability("comment", "none")}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None

    def dispatch(self, operation_name: str, request: Mapping[str, Any], *, idempotency_key: str | None):
        self.calls.append(dict(request))
        if self.error:
            raise self.error
        return {"remote_id": "comment-1"}


@pytest.fixture()
def scenario(tmp_path: Path):
    store = OrgStore(tmp_path / "approval-dispatch.sqlite3")
    mission = store.create_mission(Mission(title="dispatch", objective="atomic approval"))
    task = store.add_task(TaskSpec(
        mission_id=mission.id, dept="release", kind="comment",
        description="send approved comment",
    ))
    service = EffectApprovalService(
        store,
        principal_verifier=lambda p: p in {"approver", "executor"},
        approval_policy=lambda issuer, scope: issuer == "approver",
    )
    adapter = Adapter()
    dispatcher = ExternalEffectDispatcher(
        store, adapter, worker_id="worker-1", approval_service=service,
    )
    request = {"repository": "owner/repo", "body": "approved"}
    scope = {
        "mission_id": mission.id, "task_id": task.id,
        "repository": "owner/repo", "ref_name": "refs/heads/main",
        "commit_sha": "a" * 40, "provider_id": adapter.provider_id,
        "operation_name": "comment", "request": request,
    }
    yield store, service, adapter, dispatcher, scope
    store.close()


def issue(service, scope):
    return service.issue(
        issuer_principal_id="approver", executor_principal_id="executor",
        **scope,
    )


def execute(dispatcher, scope, token):
    return dispatcher.execute(
        scope["mission_id"], scope["task_id"], "comment", "revision-1",
        scope["request"], actor="executor", approval_token=token,
        repository=scope["repository"], ref_name=scope["ref_name"],
        commit_sha=scope["commit_sha"],
    )


def test_dispatch_consumes_approval_and_success_replay_needs_no_new_token(scenario):
    store, service, adapter, dispatcher, scope = scenario
    approval = issue(service, scope)

    first = execute(dispatcher, scope, approval.token)
    with pytest.raises(EffectNotAuthorized):
        dispatcher.execute(
            scope["mission_id"], scope["task_id"], "comment", "revision-1",
            scope["request"], actor="forged", repository=scope["repository"],
            ref_name=scope["ref_name"], commit_sha=scope["commit_sha"],
        )
    replay = dispatcher.execute(
        scope["mission_id"], scope["task_id"], "comment", "revision-1",
        scope["request"], actor="executor", repository=scope["repository"],
        ref_name=scope["ref_name"], commit_sha=scope["commit_sha"],
    )

    assert first.state == "succeeded" and not first.reused
    assert replay.state == "succeeded" and replay.reused
    assert len(adapter.calls) == 1
    assert store.effect_approval_get(approval.approval_id)["status"] == "consumed"


def test_invalid_token_does_not_consume_valid_approval_or_claim_operation(scenario):
    store, service, adapter, dispatcher, scope = scenario
    approval = issue(service, scope)

    with pytest.raises(EffectNotAuthorized):
        execute(dispatcher, scope, "invalid-token")

    assert store.effect_approval_get(approval.approval_id)["status"] == "issued"
    assert adapter.calls == []
    prepared_event = next(
        row for row in store.tail_audit(20)
        if row["action"] == "external_operation.prepared"
    )
    assert store.external_operation_get(prepared_event["ref"])["state"] == "prepared"

    result = execute(dispatcher, scope, approval.token)
    assert result.state == "succeeded"
    assert len(adapter.calls) == 1


def test_crash_after_atomic_claim_consumes_token_and_blocks_redispatch(scenario):
    store, service, adapter, dispatcher, scope = scenario
    approval = issue(service, scope)
    adapter.error = SystemExit("simulated process death")

    with pytest.raises(SystemExit):
        execute(dispatcher, scope, approval.token)

    assert store.effect_approval_get(approval.approval_id)["status"] == "consumed"
    prepared_event = next(
        row for row in store.tail_audit(20)
        if row["action"] == "external_operation.prepared"
    )
    operation = store.external_operation_get(prepared_event["ref"])
    assert operation["state"] == "in_flight"
    with pytest.raises(EffectUncertain):
        execute(dispatcher, scope, approval.token)
    assert len(adapter.calls) == 1


def test_scope_mismatch_keeps_approval_available(scenario):
    store, service, adapter, dispatcher, scope = scenario
    approval = issue(service, scope)
    altered = {**scope, "commit_sha": "b" * 40}

    with pytest.raises(EffectNotAuthorized):
        execute(dispatcher, altered, approval.token)

    assert store.effect_approval_get(approval.approval_id)["status"] == "issued"
    assert adapter.calls == []
    assert execute(dispatcher, scope, approval.token).state == "succeeded"
