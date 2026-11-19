"""اختبارات متجر التنظيم — جداول، تدقيق، حسم ادعاءات، موافقات.

القواعد المفروضة: الحسم بلا أدلة مرفوض، قرار بلا صانع مرفوض،
التدقيق لا يفوّت انتقالًا، والإدخال المكرر آمن.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from src.org.contracts import (
    Approval,
    Claim,
    Evidence,
    Finding,
    Lesson,
    Mission,
    Review,
    TaskSpec,
)
from src.org.store import OrgError, OrgStore, ORG_SCHEMA_VERSION


@pytest.fixture()
def store() -> OrgStore:
    return OrgStore(":memory:")


class TestMissions:
    def test_create_get_list(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="مهمة", objective="هدف"))
        got = store.mission_get(m.id)
        assert got is not None and got.title == "مهمة"
        assert store.mission_list() == [m]

    def test_duplicate_create_idempotent(self, store: OrgStore) -> None:
        m1 = store.create_mission(Mission(title="t", objective="o"))
        m2 = store.create_mission(Mission(title="t", objective="o"))
        assert m1.id == m2.id
        assert len(store.mission_list()) == 1

    def test_audit_trail_on_create(self, store: OrgStore) -> None:
        store.create_mission(Mission(title="t", objective="o"))
        actions = [row["action"] for row in store.tail_audit(10)]
        assert "mission.created" in actions

    def test_phase_transition_audited(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        store.mission_update(m.with_phase("B_INTEL"))
        phase_rows = [r for r in store.tail_audit(10)
                      if r["action"] == "mission.phase"]
        assert phase_rows and phase_rows[0]["details"]["to"] == "B_INTEL"


    def test_mission_resume_lock_is_exclusive_and_token_bound(
            self, tmp_path) -> None:
        db = tmp_path / "resume-lock.sqlite"
        first = OrgStore(db)
        mission = first.create_mission(Mission(title="resume", objective="exclusive"))
        second = OrgStore(db)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(first.claim_mission_resume, mission.id,
                                actor="operator-a", reason="resume"),
                    pool.submit(second.claim_mission_resume, mission.id,
                                actor="operator-b", reason="resume"),
                ]
                outcomes = []
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except OrgError:
                        outcomes.append(None)
            winners = [item for item in outcomes if item is not None]
            assert len(winners) == 1
            run = winners[0]
            with pytest.raises(OrgError, match="محجوب"):
                second.claim_mission_resume(
                    mission.id, actor="operator-c", reason="concurrent")
            with pytest.raises(OrgError, match="قديم|لا يملك"):
                second.finish_mission_resume(
                    mission.id, "wrong-token", status="completed")
            first.finish_mission_resume(
                mission.id, run["token"], status="completed")
            assert first.mission_resume_runs_for(mission.id)[0]["status"] == "completed"
            second.claim_mission_resume(
                mission.id, actor="operator-c", reason="after completion")
        finally:
            second.close()
            first.close()

    def test_orphaned_resume_lock_requires_human_reconciliation(
            self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="orphan", objective="manual"))
        store.claim_mission_resume(
            mission.id, actor="operator", reason="process interrupted")
        with pytest.raises(OrgError, match="تأكيد توقف"):
            store.abandon_mission_resume(
                mission.id, actor="operator", reason="cleanup",
                confirm_process_stopped=False)
        with pytest.raises(OrgError, match="محجوب"):
            store.claim_mission_resume(
                mission.id, actor="operator-2", reason="retry")
        store.abandon_mission_resume(
            mission.id, actor="operator", reason="verified process stopped",
            confirm_process_stopped=True)
        assert store.mission_resume_runs_for(mission.id)[0]["status"] == "abandoned"
        replacement = store.claim_mission_resume(
            mission.id, actor="operator-2", reason="explicitly authorized")
        assert replacement["status"] == "running"


class TestTasks:
    def test_task_state_machine(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        spec = store.add_task(TaskSpec(mission_id=m.id, dept="qa",
                                       kind="test", description="d"))
        store.task_set_state(spec.id, "running")
        store.task_set_state(spec.id, "done", result={"ok": True})
        task = store.task_get(spec.id)
        assert task is not None
        assert task["state"] == "done"
        assert '"ok":true' in task["result"].replace(" ", "")

    def test_unknown_task_state_rejected(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        spec = store.add_task(TaskSpec(mission_id=m.id, dept="qa",
                                       kind="test", description="d"))
        with pytest.raises(OrgError):
            store.task_set_state(spec.id, "teleported")

    def test_deterministic_task_id(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        t1 = store.add_task(TaskSpec(mission_id=m.id, dept="qa", kind="test",
                                     description="d"))
        t2 = store.add_task(TaskSpec(mission_id=m.id, dept="qa", kind="test",
                                     description="d"))
        assert t1.id == t2.id

    def test_claim_is_single_owner_and_persists_attempt(self, tmp_path) -> None:
        db = tmp_path / "claims.sqlite"
        first = OrgStore(db)
        mission = first.create_mission(Mission(title="claim", objective="atomic"))
        task = first.add_task(TaskSpec(
            mission_id=mission.id, dept="qa", kind="test", description="run"))
        second = OrgStore(db)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(first.claim_task, task.id, "worker-a"),
                    pool.submit(second.claim_task, task.id, "worker-b"),
                ]
                claims = [future.result() for future in futures]
            winners = [claim for claim in claims if claim is not None]
            assert len(winners) == 1
            claimed = winners[0]
            assert claimed["state"] == "running"
            assert claimed["idempotency_key"]
            assert claimed["input_snapshot"]
            assert len(first.task_attempts_for(task.id)) == 1
            first.finish_claimed_task(
                task.id, claimed["lease_token"], {"verified": True})
            assert first.task_get(task.id)["state"] == "done"
            assert first.task_attempts_for(task.id)[0]["status"] == "done"
        finally:
            second.close()
            first.close()

    def test_claim_rejects_stale_token_and_does_not_reclaim_running(
        self, store: OrgStore
    ) -> None:
        mission = store.create_mission(Mission(title="claim", objective="safe"))
        task = store.add_task(TaskSpec(
            mission_id=mission.id, dept="qa", kind="test", description="run"))
        claim = store.claim_task(task.id, "worker-a", lease_seconds=1)
        assert claim is not None
        assert store.claim_task(task.id, "worker-b") is None
        with pytest.raises(OrgError, match="مطالبة"):
            store.finish_claimed_task(task.id, "stale-token", {"ok": True})
        store.fail_claimed_task(task.id, claim["lease_token"], "uncertain")
        assert store.claim_task(task.id, "worker-b") is None
        attempts = store.task_attempts_for(task.id)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "failed"


    def test_heartbeat_renews_only_current_owner_and_generation(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="heartbeat", objective="renew"))
        task = store.add_task(TaskSpec(
            mission_id=mission.id, dept="qa", kind="test", description="long run"))
        claim = store.claim_task(task.id, "worker-a", lease_seconds=120)
        assert claim is not None
        assert claim["lease_generation"] == 1
        assert claim["lease_heartbeat_at"]
        renewed = store.heartbeat_task(
            task.id, "worker-a", claim["lease_token"],
            claim["lease_generation"], lease_seconds=240)
        assert renewed["lease_generation"] == 1
        assert renewed["lease_expires_at"] > claim["lease_expires_at"]
        assert store.task_attempts_for(task.id)[0]["lease_generation"] == 1
        with pytest.raises(OrgError, match="heartbeat"):
            store.heartbeat_task(
                task.id, "worker-b", claim["lease_token"],
                claim["lease_generation"], lease_seconds=240)
        with pytest.raises(OrgError, match="heartbeat"):
            store.heartbeat_task(
                task.id, "worker-a", claim["lease_token"],
                claim["lease_generation"] + 1, lease_seconds=240)

    def test_heartbeat_cannot_resurrect_expired_lease(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="expired", objective="no resurrection"))
        task = store.add_task(TaskSpec(
            mission_id=mission.id, dept="qa", kind="test", description="stopped"))
        claim = store.claim_task(task.id, "worker-a", lease_seconds=60)
        assert claim is not None
        expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        with store._conn:
            store._conn.execute(
                "UPDATE tasks SET lease_expires_at=? WHERE id=?", (expired, task.id))
        with pytest.raises(OrgError, match="انتهت lease"):
            store.heartbeat_task(
                task.id, "worker-a", claim["lease_token"],
                claim["lease_generation"], lease_seconds=300)

    def test_fencing_generation_rejects_old_worker_finalization(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="fencing", objective="reject stale generation"))
        task = store.add_task(TaskSpec(
            mission_id=mission.id, dept="qa", kind="test", description="stale"))
        claim = store.claim_task(task.id, "worker-a")
        assert claim is not None
        with store._conn:
            store._conn.execute(
                "UPDATE tasks SET lease_generation=lease_generation+1 WHERE id=?",
                (task.id,))
        with pytest.raises(OrgError, match="fencing"):
            store.finish_claimed_task(
                task.id, claim["lease_token"], {"ok": True},
                lease_generation=claim["lease_generation"])
        assert store.task_get(task.id)["state"] == "running"


class TestClaimsAndEvidence:
    def test_resolve_verified_requires_evidence(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        c = store.add_claim(Claim(mission_id=m.id, agent_role="dev:backend",
                                  statement="إصلاح مدّعى", claim_kind="fix"))
        with pytest.raises(OrgError, match="بلا أدلة"):
            store.claim_resolve(c.id, "verified", "قول", [])

    def test_resolve_with_evidence(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        c = store.add_claim(Claim(mission_id=m.id, agent_role="qa:runner",
                                  statement="اختبار نجح", claim_kind="test_pass"))
        e = store.add_evidence(Evidence(mission_id=m.id, kind="test_result",
                                        detail={"rc": 0}, ok=True,
                                        claim_id=c.id))
        resolved = store.claim_resolve(c.id, "verified", "دليل",
                                       [e.id])
        assert resolved.status == "verified"
        assert resolved.evidence_ids == [e.id]

    def test_evidence_id_includes_claim(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        e1 = store.add_evidence(Evidence(mission_id=m.id, kind="replay",
                                         detail={"x": 1}, claim_id="c1"))
        e2 = store.add_evidence(Evidence(mission_id=m.id, kind="replay",
                                         detail={"x": 1}, claim_id="c2"))
        assert e1.id != e2.id

    def test_unknown_claim_resolve_rejected(self, store: OrgStore) -> None:
        with pytest.raises(OrgError):
            store.claim_resolve("nope", "verified", "r", ["e"])


class TestApprovals:
    def test_request_and_decide(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        a = store.request_approval(Approval(mission_id=m.id, kind="merge",
                                            subject="T-1"))
        assert a.approved is None
        decided = store.decide_approval(a.id, True, "human-admin")
        assert decided.approved is True
        assert decided.decided_by == "human-admin"
        assert decided.decided_at

    def test_decide_requires_actor(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        a = store.request_approval(Approval(mission_id=m.id, kind="merge",
                                            subject="T-1"))
        with pytest.raises(OrgError):
            store.decide_approval(a.id, True, "  ")

    def test_decide_unknown_rejected(self, store: OrgStore) -> None:
        with pytest.raises(OrgError):
            store.decide_approval("nope", True, "h")



class TestMissionTokenBudgets:
    def test_budget_reservations_settle_and_persist(self, tmp_path) -> None:
        db = tmp_path / "mission-budget.sqlite"
        first = OrgStore(db)
        mission = first.create_mission(Mission(title="budget", objective="bounded"))
        first.configure_mission_token_budget(mission.id, 100)
        reservation = first.reserve_mission_output_tokens(
            mission.id, "development:backend", 60)
        assert reservation["status"] == "reserved"
        second = OrgStore(db)
        try:
            settled = second.settle_mission_output_tokens(reservation["id"], 25)
            assert settled["status"] == "settled"
            budget = first.mission_token_budget_get(mission.id)
            assert budget["reserved_output_tokens"] == 0
            assert budget["consumed_output_tokens"] == 25
            assert budget["status"] == "active"
            with pytest.raises(OrgError, match="سبق"):
                first.settle_mission_output_tokens(reservation["id"], 25)
        finally:
            second.close()
            first.close()

    def test_concurrent_reservations_cannot_overcommit_budget(self, tmp_path) -> None:
        db = tmp_path / "mission-budget-race.sqlite"
        first = OrgStore(db)
        mission = first.create_mission(Mission(title="race", objective="atomic"))
        first.configure_mission_token_budget(mission.id, 100)
        second = OrgStore(db)
        try:
            def reserve(store: OrgStore):
                try:
                    return store.reserve_mission_output_tokens(
                        mission.id, "parallel:worker", 60)
                except OrgError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(reserve, (first, second)))
            winners = [item for item in results if item is not None]
            assert len(winners) == 1
            budget = first.mission_token_budget_get(mission.id)
            assert budget["reserved_output_tokens"] == 60
            assert budget["consumed_output_tokens"] == 0
            first.settle_mission_output_tokens(winners[0]["id"], 40)
            budget = second.mission_token_budget_get(mission.id)
            assert budget["reserved_output_tokens"] == 0
            assert budget["consumed_output_tokens"] == 40
            assert budget["status"] == "active"
        finally:
            second.close()
            first.close()

    def test_budget_rejects_overspend_and_invalid_values(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="limit", objective="stop"))
        with pytest.raises(OrgError):
            store.configure_mission_token_budget(mission.id, 0)
        store.configure_mission_token_budget(mission.id, 50)
        with pytest.raises(OrgError, match="غير كافية"):
            store.reserve_mission_output_tokens(mission.id, "qa:runner", 51)
        budget = store.mission_token_budget_get(mission.id)
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] == 0
        assert budget["status"] == "active"
        with pytest.raises(OrgError, match="لا يمكن تغيير"):
            store.configure_mission_token_budget(mission.id, 100)

    def test_release_returns_reservation_without_consuming_tokens(
            self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="release", objective="refund"))
        store.configure_mission_token_budget(mission.id, 100)
        reservation = store.reserve_mission_output_tokens(
            mission.id, "qa:runner", 70)
        released = store.release_mission_output_tokens(
            reservation["id"], "provider rejected before dispatch")
        assert released["status"] == "released"
        budget = store.mission_token_budget_get(mission.id)
        assert budget["reserved_output_tokens"] == 0
        assert budget["consumed_output_tokens"] == 0


class TestLessonsMetrics:
    def test_lessons_active_order(self, store: OrgStore) -> None:
        store.add_lesson(Lesson(text="ثقة منخفضة", scope="qa",
                                confidence=0.3))
        store.add_lesson(Lesson(text="ثقة عالية", scope="qa",
                                confidence=0.9))
        texts = [lesson.text for lesson in store.lessons_active()]
        assert texts[0] == "ثقة عالية"

    def test_metrics_recorded(self, store: OrgStore) -> None:
        store.record_metric("org.completion_rate", 0.5, {})
        snap = store.metrics_snapshot()
        assert snap and snap[0]["value"] == 0.5

    def test_counts(self, store: OrgStore) -> None:
        store.create_mission(Mission(title="t", objective="o"))
        counts = store.counts()
        assert counts["missions"] == 1 and counts["tasks"] == 0

    def test_schema_version_declared(self, store: OrgStore) -> None:
        assert ORG_SCHEMA_VERSION == 11


class TestReviewsAndFindings:
    def test_review_roundtrip(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        store.add_review(Review(mission_id=m.id, task_id="tk",
                                reviewer="review:logic", lens="logic",
                                verdict="approve", score=90))
        rows = store.reviews_for(m.id)
        assert len(rows) == 1 and rows[0].score == 90

    def test_findings_status_transition(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        f = store.add_finding(Finding(mission_id=m.id, source="security",
                                      category="secret", severity="critical",
                                      description="سر"))
        store.finding_set_status(f.id, "fixed")
        rows = store.findings_for(m.id)
        assert rows[0].status == "fixed"

    def test_finding_status_rejects_unknown(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        f = store.add_finding(Finding(mission_id=m.id, source="security",
                                      category="c", severity="low",
                                      description="d"))
        with pytest.raises(OrgError):
            store.finding_set_status(f.id, "meh")

    def test_operator_mark_failed_requires_expired_lease_and_audits(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="reconcile", objective="safe"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="uncertain"))
        claim = store.claim_task(task.id, "worker", lease_seconds=60)
        assert claim is not None
        with pytest.raises(OrgError, match="انتهاء lease"):
            store.reconcile_task(task.id, "mark_failed", "operator",
                                 "inspect logs", "decision-1")
        with store._conn:
            store._conn.execute(
                "UPDATE tasks SET lease_expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", task.id))
        decision = store.reconcile_task(task.id, "mark_failed", "operator",
                                        "no side effect confirmed", "decision-1")
        assert decision["action"] == "mark_failed"
        assert store.task_get(task.id)["state"] == "failed"
        assert store.task_attempts_for(task.id)[0]["status"] == "failed"
        assert store.tail_audit(1)[0]["action"] == "task.reconciled"

    def test_operator_completion_requires_successful_evidence(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="reconcile", objective="evidence"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="verify"))
        store.task_set_state(task.id, "failed", error="interrupted")
        with pytest.raises(OrgError, match="مراجع الأدلة"):
            store.reconcile_task(task.id, "mark_completed_with_evidence",
                                 "operator", "reviewed", "decision-2", [])
        from src.org.contracts import Evidence
        evidence = store.add_evidence(Evidence(
            mission_id=mission.id, kind="test_result",
            detail={"report": "reports/test.json"}, ok=True))
        decision = store.reconcile_task(
            task.id, "mark_completed_with_evidence", "operator",
            "verified report", "decision-2", [evidence.id])
        assert decision["action"] == "mark_completed_with_evidence"
        assert store.task_get(task.id)["state"] == "done"

    def test_retry_authorization_creates_new_task_and_is_idempotent(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="retry", objective="new record"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="run once"))
        store.task_set_state(task.id, "failed", error="runner stopped", attempts=1)
        decision = store.reconcile_task(task.id, "retry_authorized", "operator",
                                        "safe after review", "retry-1")
        replacement = store.task_get(decision["replacement_task_id"])
        assert replacement is not None and replacement["state"] == "pending"
        assert replacement["id"] != task.id
        assert store.task_get(task.id)["state"] == "failed"
        again = store.reconcile_task(task.id, "retry_authorized", "operator",
                                     "safe after review", "retry-1")
        assert again["id"] == decision["id"]
        assert len(store.task_reconciliations_for(mission.id)) == 1

    def test_reconciliation_rejects_completed_and_wrong_decision_reuse(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="closed", objective="immutable"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="done"))
        store.task_set_state(task.id, "done")
        with pytest.raises(OrgError, match="لا يمكن مصالحة"):
            store.reconcile_task(task.id, "manual_hold", "operator",
                                 "hold", "closed-1")


    def test_reconciliation_key_rejects_changed_reason_or_evidence(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="idempotency", objective="strict"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="hold"))
        store.task_set_state(task.id, "failed", error="interrupted")
        store.reconcile_task(task.id, "manual_hold", "operator",
                             "first reason", "same-key")
        with pytest.raises(OrgError, match="بيانات قرار مختلفة"):
            store.reconcile_task(task.id, "manual_hold", "operator",
                                 "changed reason", "same-key")

    def test_only_one_terminal_reconciliation_per_task(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="single decision", objective="no duplicate retries"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="run"))
        store.task_set_state(task.id, "failed", error="interrupted")
        store.reconcile_task(task.id, "retry_authorized", "operator",
                             "first authorization", "retry-one")
        with pytest.raises(OrgError, match="قرار نهائي"):
            store.reconcile_task(task.id, "retry_authorized", "operator",
                                 "second authorization", "retry-two")

    def test_invalid_or_naive_lease_expiry_is_not_treated_as_expired(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="bad lease", objective="fail closed"))
        task = store.add_task(TaskSpec(mission_id=mission.id, dept="qa",
                                       kind="test", description="running"))
        claim = store.claim_task(task.id, "worker", lease_seconds=60)
        assert claim is not None
        for invalid_expiry in ("not-a-date", "2000-01-01T00:00:00"):
            with store._conn:
                store._conn.execute(
                    "UPDATE tasks SET lease_expires_at=? WHERE id=?",
                    (invalid_expiry, task.id))
            with pytest.raises(OrgError, match="انتهاء lease"):
                store.reconcile_task(task.id, "mark_failed", "operator",
                                     "cannot verify lease expiry", f"bad-{invalid_expiry}")


class TestExternalOperationLedger:
    def _prepared(self, store: OrgStore):
        mission = store.create_mission(Mission(title="external", objective="ledger"))
        task = store.add_task(TaskSpec(
            mission_id=mission.id, dept="development", kind="external",
            description="create remote issue"))
        row = store.prepare_external_operation(
            mission.id, task.id, "github.issue.create", "rev-1",
            {"repository": "acme/project", "title": "Bug"})
        return mission, task, row

    def test_prepare_is_stable_and_rejects_changed_payload(self, store: OrgStore) -> None:
        mission, task, first = self._prepared(store)
        again = store.prepare_external_operation(
            mission.id, task.id, "github.issue.create", "rev-1",
            {"title": "Bug", "repository": "acme/project"})
        assert first["operation_key"] == again["operation_key"]
        assert first["request_fingerprint"] == again["request_fingerprint"]
        with pytest.raises(OrgError, match="بصمة"):
            store.prepare_external_operation(
                mission.id, task.id, "github.issue.create", "rev-1",
                {"repository": "acme/project", "title": "Different"})

    def test_claim_finalize_and_restart_persist(self, tmp_path) -> None:
        db = tmp_path / "external-ledger.sqlite"
        first = OrgStore(db)
        mission, task, prepared = self._prepared(first)
        claim = first.claim_external_operation(prepared["operation_key"], "worker-a")
        done = first.finish_external_operation(
            prepared["operation_key"], claim["attempt_token"],
            state="succeeded", result={"remote_id": 42})
        assert done["state"] == "succeeded"
        second = OrgStore(db)
        try:
            restored = second.external_operation_get(prepared["operation_key"])
            assert restored is not None and restored["state"] == "succeeded"
            assert len(second.external_operation_attempts_for(
                prepared["operation_key"])) == 1
        finally:
            second.close()
            first.close()

    def test_uncertain_result_blocks_automatic_reclaim(self, store: OrgStore) -> None:
        _, _, prepared = self._prepared(store)
        claim = store.claim_external_operation(prepared["operation_key"], "worker-a")
        store.finish_external_operation(
            prepared["operation_key"], claim["attempt_token"],
            state="uncertain", error="timeout after request dispatch")
        with pytest.raises(OrgError, match="uncertain"):
            store.claim_external_operation(prepared["operation_key"], "worker-b")

    def test_stale_attempt_token_cannot_finalize(self, store: OrgStore) -> None:
        _, _, prepared = self._prepared(store)
        claim = store.claim_external_operation(prepared["operation_key"], "worker-a")
        with pytest.raises(OrgError, match="قديم"):
            store.finish_external_operation(
                prepared["operation_key"], "stale-token", state="succeeded",
                result={"remote_id": 1})
        assert store.external_operation_get(prepared["operation_key"])["state"] == "in_flight"
        store.finish_external_operation(
            prepared["operation_key"], claim["attempt_token"],
            state="failed_definitive", error="provider rejected")



    def test_recovered_in_flight_operation_becomes_uncertain_and_stays_blocked(
            self, tmp_path) -> None:
        db = tmp_path / "external-recovery.sqlite"
        first = OrgStore(db)
        _, _, prepared = self._prepared(first)
        claim = first.claim_external_operation(prepared["operation_key"], "worker-a")
        first.close()

        recovered = OrgStore(db)
        try:
            uncertain = recovered.mark_external_operation_uncertain(
                prepared["operation_key"], claim["attempt_token"],
                "worker process disappeared during dispatch")
            assert uncertain["state"] == "uncertain"
            with pytest.raises(OrgError, match="uncertain"):
                recovered.claim_external_operation(prepared["operation_key"], "worker-b")
            assert recovered.external_operation_attempts_for(
                prepared["operation_key"])[0]["state"] == "uncertain"
        finally:
            recovered.close()

    def test_uncertain_operation_requires_explicit_evidence_to_reconcile(
            self, store: OrgStore) -> None:
        _, _, prepared = self._prepared(store)
        claim = store.claim_external_operation(prepared["operation_key"], "worker-a")
        store.mark_external_operation_uncertain(
            prepared["operation_key"], claim["attempt_token"], "response lost")
        with pytest.raises(OrgError, match="أدلة المصالحة"):
            store.reconcile_external_operation(
                prepared["operation_key"], claim["attempt_token"],
                outcome="succeeded", evidence={}, reconciled_by="operator")
        reconciled = store.reconcile_external_operation(
            prepared["operation_key"], claim["attempt_token"],
            outcome="succeeded",
            evidence={"provider": "github", "remote_id": 42, "verified": True},
            reconciled_by="operator")
        assert reconciled["state"] == "reconciled"
        assert '"remote_id":42' in reconciled["result_payload"]
        with pytest.raises(OrgError, match="reconciled"):
            store.claim_external_operation(prepared["operation_key"], "worker-b")

    def test_reconciliation_evidence_is_bounded_before_persistence(
            self, store: OrgStore) -> None:
        _, _, prepared = self._prepared(store)
        claim = store.claim_external_operation(prepared["operation_key"], "worker-a")
        store.mark_external_operation_uncertain(
            prepared["operation_key"], claim["attempt_token"], "response lost")

        oversized = {"provider_response": "x" * (16 * 1024)}
        with pytest.raises(OrgError, match="تتجاوز الحد الأقصى"):
            store.reconcile_external_operation(
                prepared["operation_key"], claim["attempt_token"],
                outcome="succeeded", evidence=oversized, reconciled_by="operator")

        operation = store.external_operation_get(prepared["operation_key"])
        assert operation["state"] == "uncertain"
        assert operation["result_payload"] == ""
        assert not any(
            row["action"] == "external_operation.reconciled"
            for row in store.tail_audit(20)
        )


    def test_missing_task_or_mission_is_rejected(self, store: OrgStore) -> None:
        mission = store.create_mission(Mission(title="missing", objective="fail closed"))
        with pytest.raises(OrgError, match="المهمة الفرعية"):
            store.prepare_external_operation(
                mission.id, "missing-task", "provider.write", "1", {"x": 1})
