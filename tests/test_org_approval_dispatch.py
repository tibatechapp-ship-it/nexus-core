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
    """Two independent SQLite connections racing one token must never dispatch twice."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

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
    verifier = lambda principal: principal in {"approver", "executor"}
    policy = lambda issuer, scope: issuer == "approver"
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

    entered_a, entered_b, release = Event(), Event(), Event()

    class BlockingAdapter:
        provider_id = "scm-race"
        capabilities = {"comment": EffectCapability("comment", "none")}

        def __init__(self, entered):
            self.entered = entered
            self.calls = 0

        def dispatch(self, operation_name, payload, *, idempotency_key):
            self.calls += 1
            self.entered.set()
            assert release.wait(5), "test did not release the winning provider call"
            return {"remote_id": "race-1"}

    adapter_a = BlockingAdapter(entered_a)
    adapter_b = BlockingAdapter(entered_b)
    dispatcher_a = ExternalEffectDispatcher(
        store_a, adapter_a, worker_id="race-worker-a", approval_service=service_a,
    )
    dispatcher_b = ExternalEffectDispatcher(
        store_b, adapter_b, worker_id="race-worker-b", approval_service=service_b,
    )
    start = Barrier(2)

    def run(dispatcher):
        start.wait(timeout=5)
        return dispatcher.execute(
            mission.id, task.id, "comment", "race-revision", request,
            actor="executor", approval_token=approval.token,
            repository=scope["repository"], ref_name=scope["ref_name"],
            commit_sha=scope["commit_sha"],
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(run, dispatcher_a)
            future_b = pool.submit(run, dispatcher_b)
            assert entered_a.wait(3) or entered_b.wait(3), (
                "neither contender reached the provider adapter"
            )
            # Identify the winner by the adapter it entered; keep it in-flight
            # while the other independent connection attempts the same token.
            if entered_a.is_set():
                winner, loser, winner_adapter = future_a, future_b, adapter_a
            else:
                winner, loser, winner_adapter = future_b, future_a, adapter_b
            with pytest.raises((EffectNotAuthorized, EffectUncertain)):
                loser.result(timeout=3)
            release.set()
            winner_result = winner.result(timeout=5)
            assert winner_result.state == "succeeded"
            assert not winner_result.reused
            assert winner_adapter.calls == 1
            assert adapter_a.calls + adapter_b.calls == 1
        assert store_a.effect_approval_get(approval.approval_id)["status"] == "consumed"
    finally:
        release.set()
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
