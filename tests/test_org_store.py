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
        assert ORG_SCHEMA_VERSION == 2


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
