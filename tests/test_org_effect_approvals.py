"""Security and concurrency tests for durable scoped effect approvals."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest

from src.org.contracts import Mission
from src.org.effect_approvals import EffectApprovalError, EffectApprovalService
from src.org.store import OrgStore


@pytest.fixture()
def scenario(tmp_path: Path):
    store = OrgStore(tmp_path / "approvals.sqlite3")
    mission = store.create_mission(Mission(title="approval", objective="test scoped approval"))
    service = EffectApprovalService(
        store,
        principal_verifier=lambda principal: principal in {"reviewer-1", "operator-1"},
        approval_policy=lambda issuer, scope: (
            issuer == "reviewer-1" and scope["repository"] == "owner/repo"
            and scope["operation_name"] == "comment"
        ),
    )
    args = {
        "mission_id": mission.id, "task_id": "task-1",
        "repository": "owner/repo", "ref_name": "refs/heads/release",
        "commit_sha": "a" * 40, "provider_id": "scm-test",
        "operation_name": "comment", "request": {"body": "approved"},
    }
    yield store, service, args
    store.close()


def _issue(service, args, **overrides):
    return service.issue(
        issuer_principal_id="reviewer-1", executor_principal_id="operator-1",
        **{**args, **overrides})


def _consume(service, token, args, **overrides):
    return service.consume(
        token, executor_principal_id="operator-1", **{**args, **overrides})


def test_token_is_not_stored_and_exact_scope_consumes_once(scenario):
    store, service, args = scenario
    approval = _issue(service, args)
    row = store.effect_approval_get(approval.approval_id)
    assert approval.token not in str(row)
    assert _consume(service, approval.token, args)["status"] == "consumed"
    with pytest.raises(EffectApprovalError, match="consumed"):
        _consume(service, approval.token, args)


@pytest.mark.parametrize("change", [
    {"repository": "other/repo"}, {"ref_name": "refs/heads/main"},
    {"commit_sha": "b" * 40}, {"provider_id": "other-provider"},
    {"operation_name": "delete_repository"}, {"request": {"body": "tampered"}},
    {"task_id": "other-task"},
])
def test_scope_or_payload_mismatch_does_not_consume(scenario, change):
    _, service, args = scenario
    approval = _issue(service, args)
    with pytest.raises(EffectApprovalError, match="نطاق التفويض"):
        _consume(service, approval.token, {**args, **change})
    assert _consume(service, approval.token, args)["status"] == "consumed"


def test_wrong_authenticated_executor_is_rejected(scenario):
    _, service, args = scenario
    approval = _issue(service, args)
    with pytest.raises(EffectApprovalError, match="صاحب التفويض"):
        service.consume(approval.token, executor_principal_id="reviewer-1", **args)


def test_unverified_identity_and_unauthorized_issuer_are_rejected(scenario):
    _, service, args = scenario
    with pytest.raises(EffectApprovalError, match="not authenticated"):
        service.issue(issuer_principal_id="forged",
                      executor_principal_id="operator-1", **args)
    with pytest.raises(EffectApprovalError, match="not authorized"):
        service.issue(issuer_principal_id="operator-1",
                      executor_principal_id="operator-1", **args)


def test_revoked_approval_cannot_be_consumed(scenario):
    store, service, args = scenario
    approval = _issue(service, args)
    service.revoke(approval.approval_id, issuer_principal_id="reviewer-1",
                   reason="release was paused")
    assert store.effect_approval_get(approval.approval_id)["status"] == "revoked"
    with pytest.raises(EffectApprovalError, match="revoked"):
        _consume(service, approval.token, args)


def test_expired_approval_is_persistently_marked(scenario):
    store, service, args = scenario
    approval = _issue(service, args, ttl_seconds=1)
    time.sleep(1.05)
    with pytest.raises(EffectApprovalError, match="انتهت صلاحية"):
        _consume(service, approval.token, args)
    assert store.effect_approval_get(approval.approval_id)["status"] == "expired"


def test_concurrent_consumption_has_exactly_one_winner(scenario):
    _, service, args = scenario
    approval = _issue(service, args)

    def attempt():
        try:
            _consume(service, approval.token, args)
            return "consumed"
        except EffectApprovalError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(8)))
    assert outcomes.count("consumed") == 1
    assert outcomes.count("rejected") == 7
