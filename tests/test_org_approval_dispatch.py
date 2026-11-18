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


def test_concurrent_consumption_from_independent_sqlite_connections_has_one_winner(
    tmp_path: Path,
):
    """Two independent SQLite connections racing one token must yield one claim."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import hashlib
    import json

    db_path = tmp_path / "approval-race.sqlite3"
    store_a = OrgStore(db_path)
    store_b = OrgStore(db_path)
    mission = store_a.create_mission(
        Mission(title="race", objective="single-use approval under contention")
    )
    task = store_a.add_task(TaskSpec(
        mission_id=mission.id, dept="release", kind="comment",
        description="race one approved effect",
    ))
    def verifier(principal: str) -> bool:
        return principal in {"approver", "executor"}

    def policy(issuer: str, scope: Mapping[str, str]) -> bool:
        return issuer == "approver"
    service_a = EffectApprovalService(
        store_a, principal_verifier=verifier, approval_policy=policy,
    )
    service_b = EffectApprovalService(
        store_b, principal_verifier=verifier, approval_policy=policy,
    )
    request = {"repository": "owner/race-repo", "body": "one dispatch"}
    scope = {
        "mission_id": mission.id, "task_id": task.id,
        "repository": "owner/race-repo", "ref_name": "refs/heads/main",
        "commit_sha": "c" * 40, "provider_id": "scm-race",
        "operation_name": "comment", "request": request,
    }
    approval = service_a.issue(
        issuer_principal_id="approver", executor_principal_id="executor",
        **scope,
    )
    target = json.dumps(
        [scope["repository"], scope["ref_name"], scope["commit_sha"]],
        ensure_ascii=False, separators=(",", ":"),
    )
    target_fingerprint = hashlib.sha256(target.encode("utf-8")).hexdigest()
    operation = store_a.prepare_external_operation(
        mission.id, task.id, "scm-race:comment",
        "race-revision:" + target_fingerprint, request,
    )
    start = Barrier(2)

    def consume(service, worker_id):
        start.wait(timeout=5)
        return service.consume_and_claim(
            approval.token, executor_principal_id="executor",
            mission_id=mission.id, task_id=task.id,
            repository=scope["repository"], ref_name=scope["ref_name"],
            commit_sha=scope["commit_sha"], provider_id="scm-race",
            operation_name="comment", request=request,
            operation_key=operation["operation_key"], worker_id=worker_id,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(consume, service_a, "race-worker-a"),
                pool.submit(consume, service_b, "race-worker-b"),
            ]
            outcomes = []
            failures = []
            for future in futures:
                try:
                    outcomes.append(future.result(timeout=10))
                except EffectApprovalError as exc:
                    failures.append(exc)
            assert len(outcomes) == 1
            assert len(failures) == 1
            assert outcomes[0]["state"] == "in_flight"
            assert outcomes[0]["reused"] is False
        persisted = store_a.external_operation_get(operation["operation_key"])
        assert persisted["state"] == "in_flight"
        assert persisted["attempt_count"] == 1
        assert store_a.effect_approval_get(approval.approval_id)["status"] == "consumed"
        consumed_events = [
            row for row in store_a.tail_audit(50)
            if row["action"] == "effect_approval.consumed"
            and row["ref"] == approval.approval_id
        ]
        assert len(consumed_events) == 1
    finally:
        store_b.close()
        store_a.close()


def test_failed_attempt_insert_rolls_back_approval_consumption(scenario):
    """A failure after token UPDATE must roll back the entire SQLite unit."""
    store, service, adapter, dispatcher, scope = scenario
    approval = issue(service, scope)
    operation = store.prepare_external_operation(
        scope["mission_id"], scope["task_id"], "scm-test:comment",
        "revision-1:" + __import__("hashlib").sha256(
            __import__("json").dumps(
                [scope["repository"], scope["ref_name"], scope["commit_sha"]],
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        scope["request"],
    )
    store._conn.execute(
        """CREATE TRIGGER reject_external_attempt
           BEFORE INSERT ON external_operation_attempts
           BEGIN SELECT RAISE(ABORT, 'injected attempt insert failure'); END"""
    )

    with pytest.raises(EffectNotAuthorized):
        execute(dispatcher, scope, approval.token)

    assert store.effect_approval_get(approval.approval_id)["status"] == "issued"
    assert store.external_operation_get(operation["operation_key"])["state"] == "prepared"
    assert not any(
        row["action"] == "effect_approval.consumed"
        and row["ref"] == approval.approval_id
        for row in store.tail_audit(50)
    )

    store._conn.execute("DROP TRIGGER reject_external_attempt")
    result = execute(dispatcher, scope, approval.token)
    assert result.state == "succeeded"
    assert len(adapter.calls) == 1
