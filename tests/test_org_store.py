"""اختبارات متجر التنظيم — جداول، تدقيق، حسم ادعاءات، موافقات.

القواعد المفروضة: الحسم بلا أدلة مرفوض، قرار بلا صانع مرفوض،
التدقيق لا يفوّت انتقالًا، والإدخال المكرر آمن.
"""

from __future__ import annotations

import pytest
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
        assert ORG_SCHEMA_VERSION == 4


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
