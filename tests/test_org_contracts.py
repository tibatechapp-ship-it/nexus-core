"""اختبارات عقود التنظيم — الآلات المعلنة وقواعد الأدلة والموافقات.

ما يُفرض هنا هو قلب التنظيم: لا انتقال طور خارج الآلة، لا ادعاء
«محقَّق» بلا أدلة، لا موافقة مجهولة، ومعرّفات حتمية عبر التشغيلات.
"""

from __future__ import annotations

import pytest

from src.org.contracts import (
    ALLOWED_PHASE_TRANSITIONS,
    Approval,
    Claim,
    Evidence,
    Finding,
    Lesson,
    Mission,
    Review,
    TaskSpec,
    new_id,
)
from src.org.store import OrgError, OrgStore


@pytest.fixture()
def store() -> OrgStore:
    return OrgStore(":memory:")


class TestMachines:
    """الآلات المعلنة — أطوار وحالات وأصناف."""

    def test_phase_transitions_cover_all_phases(self) -> None:
        for phase in ALLOWED_PHASE_TRANSITIONS:
            assert phase in ("A_REQUIREMENTS", "B_INTEL", "C_DEVELOP",
                             "D_REVIEW", "E_TESTING", "F_VERIFICATION",
                             "G_RELEASE", "FAILED", "CANCELLED")

    def test_no_autonomous_merge_escape(self) -> None:
        """لا طور يقفز إلى G_RELEASE إلا من F_VERIFICATION."""
        for phase, allowed in ALLOWED_PHASE_TRANSITIONS.items():
            if "G_RELEASE" in allowed:
                assert phase == "F_VERIFICATION"

    def test_mission_rejects_bad_phase(self) -> None:
        with pytest.raises(ValueError):
            Mission(title="t", objective="o", phase="Z_UNKNOWN")

    def test_task_spec_rejects_unknown_dept(self) -> None:
        with pytest.raises(ValueError):
            TaskSpec(mission_id="m", dept="marketing", kind="x",
                     description="d")

    def test_review_rejects_unknown_lens(self) -> None:
        with pytest.raises(ValueError):
            Review(mission_id="m", task_id="t", reviewer="r",
                   lens="gossip", verdict="approve", score=80)

    def test_review_score_bounds(self) -> None:
        with pytest.raises(ValueError):
            Review(mission_id="m", task_id="t", reviewer="r", lens="logic",
                   verdict="approve", score=150)


class TestEvidenceRules:
    """قواعد الأدلة — لا تصديق شفوي."""

    def test_verified_claim_requires_evidence(self) -> None:
        with pytest.raises(ValueError, match="بلا أدلة"):
            Claim(mission_id="m", agent_role="dev:backend",
                  statement="أصلحت الشيء", status="verified")

    def test_claim_with_evidence_ok(self) -> None:
        claim = Claim(mission_id="m", agent_role="dev:backend",
                      statement="أصلحت", status="verified",
                      evidence_ids=["e1"])
        assert claim.status == "verified"

    def test_evidence_kind_declared(self) -> None:
        with pytest.raises(ValueError):
            Evidence(mission_id="m", kind="vibes")

    def test_evidence_summary_deterministic(self) -> None:
        e1 = Evidence(mission_id="m", kind="test_result",
                      detail={"rc": 0}, captured_by="qa:runner")
        e2 = Evidence(mission_id="m", kind="test_result",
                      detail={"rc": 0}, captured_by="qa:runner")
        assert e1.summary() == e2.summary()
        assert "نجح" in e1.summary()


class TestApprovals:
    """الموافقات البشرية — لا قرار مجهول."""

    def test_decision_needs_actor(self) -> None:
        with pytest.raises(ValueError):
            Approval(mission_id="m", kind="merge", subject="T-1",
                     approved=True, decided_by="")

    def test_approval_defaults_pending(self) -> None:
        a = Approval(mission_id="m", kind="merge", subject="T-1")
        assert a.approved is None
        assert a.decide(True, "human").approved is True

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValueError):
            Approval(mission_id="m", kind="autodeploy", subject="x")


class TestDeterminism:
    """المعرّفات الحتمية — نفس المحتوى نفس المعرّف."""

    def test_new_id_stable(self) -> None:
        assert new_id("x", "a", "b") == new_id("x", "a", "b")

    def test_mission_id_stable_in_store(self, store: OrgStore) -> None:
        m1 = store.create_mission(Mission(title="t", objective="o"))
        m2 = store.create_mission(Mission(title="t", objective="o"))
        assert m1.id == m2.id and m1.id.startswith("org-m-")

    def test_finding_requires_severity(self) -> None:
        with pytest.raises(ValueError):
            Finding(mission_id="m", source="security", category="c",
                    severity="catastrophic", description="d")

    def test_lesson_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            Lesson(text="t", scope="qa", confidence=1.5)

    def test_lesson_bump_immutable(self) -> None:
        lesson = Lesson(text="t", scope="qa", applied_count=1)
        bumped = lesson.bumped()
        assert lesson.applied_count == 1 and bumped.applied_count == 2


class TestPhaseEnforcement:
    """فرض آلة الأطوار في المتجر."""

    def test_legal_transition(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        m2 = store.mission_update(m.with_phase("B_INTEL"))
        assert m2.phase == "B_INTEL"

    def test_illegal_transition_rejected(self, store: OrgStore) -> None:
        m = store.create_mission(Mission(title="t", objective="o"))
        with pytest.raises(OrgError, match="غير قانوني"):
            store.mission_update(m.with_phase("G_RELEASE"))
        with pytest.raises(OrgError, match="غير قانوني"):
            store.mission_update(m.with_phase("C_DEVELOP"))

    def test_review_loop_is_declared(self, store: OrgStore) -> None:
        """العودة من المراجعة إلى التطوير مسموحة (دورة مقيّدة)."""
        assert "C_DEVELOP" in ALLOWED_PHASE_TRANSITIONS["D_REVIEW"]
