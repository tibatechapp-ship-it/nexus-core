"""End-to-end offline tests for dry-run effects through the durable dispatcher."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from src.org.contracts import Mission, TaskSpec
from src.org.dry_run_effects import DryRunEffectAdapter
from src.org.external_effects import (
    EffectNotAuthorized,
    EffectUncertain,
    ExternalEffectDispatcher,
)
from src.org.store import OrgStore


def _scenario(tmp_path: Path, adapter: DryRunEffectAdapter | None = None):
    store = OrgStore(tmp_path / "dry-run-dispatch.sqlite3")
    mission = store.create_mission(
        Mission(title="dry-run integration", objective="verify durable simulation")
    )
    task = store.add_task(TaskSpec(
        mission_id=mission.id,
        dept="release",
        kind="comment",
        description="simulate an approved repository comment",
    ))
    provider = adapter or DryRunEffectAdapter(["comment"])
    dispatcher = ExternalEffectDispatcher(
        store,
        provider,
        worker_id="dry-run-test-worker",
        authorizer=lambda actor, mid, tid, provider_id, operation, payload: (
            actor == "operator"
            and mid == mission.id
            and tid == task.id
            and provider_id == "dry-run"
            and operation == "comment"
            and payload.get("repository") == "owner/repo"
        ),
    )
    return store, mission, task, provider, dispatcher


def test_dispatcher_persists_simulation_marker_and_reuses_without_redispatch(
    tmp_path: Path,
) -> None:
    store, mission, task, adapter, dispatcher = _scenario(tmp_path)
    request = {"repository": "owner/repo", "body": "simulation only"}
    try:
        first = dispatcher.execute(
            mission.id, task.id, "comment", "revision-1", request,
            actor="operator",
        )
        second = dispatcher.execute(
            mission.id, task.id, "comment", "revision-1",
            {"body": "simulation only", "repository": "owner/repo"},
            actor="operator",
        )

        assert first.state == "succeeded"
        assert first.result["dry_run"] is True
        assert first.result["simulated"] is True
        assert first.result["provider_id"] == "dry-run"
        assert first.reused is False
        assert second.reused is True
        assert second.result == first.result
        assert len(adapter.calls) == 1

        row = store.external_operation_get(first.operation_key)
        assert row["state"] == "succeeded"
        assert '"dry_run": true' in row["result_payload"]
        attempts = store.external_operation_attempts_for(first.operation_key)
        assert len(attempts) == 1
    finally:
        store.close()


def test_dispatcher_authorization_denial_does_not_create_ledger_entry(
    tmp_path: Path,
) -> None:
    store, mission, task, adapter, dispatcher = _scenario(tmp_path)
    try:
        with pytest.raises(EffectNotAuthorized):
            dispatcher.execute(
                mission.id, task.id, "comment", "revision-1",
                {"repository": "owner/repo", "body": "not approved"},
                actor="untrusted",
            )
        assert adapter.calls == ()
        assert not any(
            row["action"] == "external_operation.prepared"
            for row in store.tail_audit(50)
        )
    finally:
        store.close()


class _SimulatedProcessCrash(BaseException):
    """Escape normal exception handling to model abrupt process termination."""


class _CrashAfterRecordingAdapter(DryRunEffectAdapter):
    def dispatch(
        self,
        operation_name: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> Mapping[str, Any]:
        super().dispatch(
            operation_name, request, idempotency_key=idempotency_key
        )
        raise _SimulatedProcessCrash()


def test_crash_after_dispatch_claim_leaves_in_flight_and_blocks_replay(
    tmp_path: Path,
) -> None:
    adapter = _CrashAfterRecordingAdapter(["comment"])
    store, mission, task, _, dispatcher = _scenario(tmp_path, adapter)
    request = {"repository": "owner/repo", "body": "may have been simulated"}
    try:
        with pytest.raises(_SimulatedProcessCrash):
            dispatcher.execute(
                mission.id, task.id, "comment", "revision-1", request,
                actor="operator",
            )

        operation = store.prepare_external_operation(
            mission.id, task.id, "dry-run:comment", "revision-1", request
        )
        assert operation["state"] == "in_flight"

        with pytest.raises(EffectUncertain, match="automatic redispatch is blocked"):
            dispatcher.execute(
                mission.id, task.id, "comment", "revision-1", request,
                actor="operator",
            )
        assert len(adapter.calls) == 1
        assert store.external_operation_get(operation["operation_key"])["state"] == "in_flight"
    finally:
        store.close()
