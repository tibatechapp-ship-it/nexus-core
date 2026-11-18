"""Offline tests for the approval-gated external-effect dispatcher."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from src.org.contracts import Mission, TaskSpec
from src.org.external_effects import (
    DefinitiveEffectError,
    EffectCapability,
    EffectDispatchError,
    EffectNotAuthorized,
    EffectUncertain,
    ExternalEffectDispatcher,
)
from src.org.store import OrgError, OrgStore


class FakeAdapter:
    provider_id = "fake-scm"
    capabilities = {
        "comment": EffectCapability(
            "comment", "provider_key",
            idempotency_scope="one repository + one comment operation",
            retention_seconds=86_400,
        ),
        "open_change": EffectCapability("open_change", "none"),
    }

    def __init__(self, result: Mapping[str, Any] | None = None) -> None:
        self.result = dict(result or {"remote_id": "effect-1"})
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self.error: BaseException | None = None

    def dispatch(
        self,
        operation_name: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        self.calls.append((operation_name, dict(request), idempotency_key))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture()
def setup(tmp_path: Path):
    store = OrgStore(tmp_path / "effects.sqlite3")
    mission = store.create_mission(Mission(title="effect", objective="test dispatch"))
    task = store.add_task(TaskSpec(
        mission_id=mission.id, dept="release", kind="comment",
        description="post an approved comment",
    ))
    adapter = FakeAdapter()
    dispatcher = ExternalEffectDispatcher(
        store, adapter, worker_id="test-worker",
        authorizer=lambda actor, mid, tid, provider, op, payload: actor == "operator",
    )
    yield store, mission, task, adapter, dispatcher
    store.close()


def test_success_is_persisted_and_reused_without_second_dispatch(setup) -> None:
    store, mission, task, adapter, dispatcher = setup
    first = dispatcher.execute(
        mission.id, task.id, "comment", "1",
        {"repository": "owner/repo", "body": "approved"},
        actor="operator",
    )
    second = dispatcher.execute(
        mission.id, task.id, "comment", "1",
        {"body": "approved", "repository": "owner/repo"},
        actor="operator",
    )

    assert first.state == "succeeded"
    assert first.reused is False
    assert second.reused is True
    assert second.result == {"remote_id": "effect-1"}
    assert len(adapter.calls) == 1
    assert adapter.calls[0][2] == first.operation_key
    assert store.external_operation_get(first.operation_key)["state"] == "succeeded"
    assert len(store.external_operation_attempts_for(first.operation_key)) == 1


def test_provider_without_idempotency_gets_no_key_and_only_one_attempt(setup) -> None:
    store, mission, task, adapter, dispatcher = setup
    result = dispatcher.execute(
        mission.id, task.id, "open_change", "1",
        {"head": "feature", "base": "main"},
        actor="operator",
    )
    assert result.state == "succeeded"
    assert adapter.calls[0][2] is None
    assert len(store.external_operation_attempts_for(result.operation_key)) == 1


def test_denied_approval_never_prepares_or_dispatches(setup) -> None:
    store, mission, task, adapter, _ = setup
    denied = ExternalEffectDispatcher(
        store, adapter, worker_id="worker",
        authorizer=lambda *args: False,
    )
    with pytest.raises(EffectNotAuthorized):
        denied.execute(
            mission.id, task.id, "comment", "1", {"body": "no"}, actor="intruder"
        )
    assert adapter.calls == []
    assert not any(
        row["action"] == "external_operation.prepared"
        for row in store.tail_audit(20)
    )


def test_undeclared_operation_fails_before_authorization_or_dispatch(setup) -> None:
    store, mission, task, adapter, _ = setup
    calls: list[bool] = []
    dispatcher = ExternalEffectDispatcher(
        store, adapter, worker_id="worker",
        authorizer=lambda *args: calls.append(True) or True,
    )
    with pytest.raises(EffectDispatchError, match="does not declare"):
        dispatcher.execute(
            mission.id, task.id, "delete_repository", "1", {}, actor="operator"
        )
    assert calls == []
    assert adapter.calls == []


def test_uncertain_provider_failure_is_never_redispatched(setup) -> None:
    store, mission, task, adapter, dispatcher = setup
    adapter.error = TimeoutError("provider may have committed")
    args = (mission.id, task.id, "comment", "timeout-1", {"body": "maybe sent"})
    with pytest.raises(EffectUncertain):
        dispatcher.execute(*args, actor="operator")

    rows = store.tail_audit(20)
    operation_key = next(
        row["ref"] for row in rows if row["action"] == "external_operation.finalized"
    )
    assert store.external_operation_get(operation_key)["state"] == "uncertain"
    with pytest.raises(EffectUncertain):
        dispatcher.execute(*args, actor="operator")
    assert len(adapter.calls) == 1
    assert len(store.external_operation_attempts_for(operation_key)) == 1


def test_definitive_provider_rejection_is_recorded_and_not_retried(setup) -> None:
    store, mission, task, adapter, dispatcher = setup
    adapter.error = DefinitiveEffectError("rejected")
    args = (mission.id, task.id, "comment", "rejected-1", {"body": "invalid"})
    with pytest.raises(EffectDispatchError, match="definitively rejected"):
        dispatcher.execute(*args, actor="operator")

    operation = next(
        row for row in store.tail_audit(20)
        if row["action"] == "external_operation.finalized"
    )
    assert store.external_operation_get(operation["ref"])["state"] == "failed_definitive"
    with pytest.raises(EffectDispatchError, match="previously failed"):
        dispatcher.execute(*args, actor="operator")
    assert len(adapter.calls) == 1


def test_same_identity_with_changed_payload_is_rejected(setup) -> None:
    _, mission, task, adapter, dispatcher = setup
    dispatcher.execute(
        mission.id, task.id, "comment", "same-revision",
        {"body": "original"}, actor="operator",
    )
    with pytest.raises(OrgError, match="بصمة طلب مختلفة"):
        dispatcher.execute(
            mission.id, task.id, "comment", "same-revision",
            {"body": "changed"}, actor="operator",
        )
    assert len(adapter.calls) == 1


def test_capability_rejects_undocumented_or_invalid_provider_guarantees() -> None:
    with pytest.raises(ValueError, match="documented scope"):
        EffectCapability("comment", "provider_key")
    with pytest.raises(ValueError, match="positive integer"):
        EffectCapability("comment", "provider_key", "repo", 0)
    with pytest.raises(ValueError, match="metadata is invalid"):
        EffectCapability("comment", "none", "repo")


def test_process_crash_after_claim_leaves_in_flight_and_blocks_replay(setup) -> None:
    store, mission, task, adapter, dispatcher = setup
    adapter.error = SystemExit("simulated process termination")
    args = (mission.id, task.id, "comment", "crash-window-1", {"body": "sent?"})

    with pytest.raises(SystemExit):
        dispatcher.execute(*args, actor="operator")

    row = next(
        item for item in store.tail_audit(20)
        if item["action"] == "external_operation.prepared"
    )
    operation = store.external_operation_get(row["ref"])
    assert operation["state"] == "in_flight"
    with pytest.raises(EffectUncertain, match="in_flight"):
        dispatcher.execute(*args, actor="operator")
    assert len(adapter.calls) == 1
    assert len(store.external_operation_attempts_for(row["ref"])) == 1


def test_provider_identity_is_part_of_durable_operation_identity(setup) -> None:
    store, mission, task, adapter, dispatcher = setup
    first = dispatcher.execute(
        mission.id, task.id, "comment", "provider-scope-1",
        {"body": "same logical payload"}, actor="operator",
    )
    other_adapter = FakeAdapter({"remote_id": "other-provider"})
    other_adapter.provider_id = "fake-scm-secondary"
    other_dispatcher = ExternalEffectDispatcher(
        store, other_adapter, worker_id="secondary-worker",
        authorizer=lambda *args: True,
    )
    second = other_dispatcher.execute(
        mission.id, task.id, "comment", "provider-scope-1",
        {"body": "same logical payload"}, actor="operator",
    )
    assert first.operation_key != second.operation_key
    assert len(adapter.calls) == 1
    assert len(other_adapter.calls) == 1


def test_authorizer_cannot_mutate_the_approved_dispatch_payload(setup) -> None:
    store, mission, task, adapter, _ = setup

    def mutating_authorizer(actor, mid, tid, provider, operation, payload):
        payload["body"] = "mutated after approval"
        return True

    dispatcher = ExternalEffectDispatcher(
        store, adapter, worker_id="mutation-test",
        authorizer=mutating_authorizer,
    )
    result = dispatcher.execute(
        mission.id, task.id, "comment", "immutable-payload-1",
        {"body": "approved original"}, actor="operator",
    )
    assert adapter.calls[0][1]["body"] == "approved original"
    operation = store.external_operation_get(result.operation_key)
    assert '"body":"approved original"' in operation["request_payload"]
