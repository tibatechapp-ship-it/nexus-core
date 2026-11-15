"""اختبارات التحقق المستقل — حسم بالأدلة المرتبطة وإعادة إنتاج حقيقية.

القواعد المفروضة: دليل ادعاء آخر لا يثبت ادعاءً (حتى لو نجح)، الأساس
الأخضر لا يعفي رقعة حمراء، وإعادة الإنتاج فشلها تُسقط الإصلاح.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.org.agents import AgentRuntime, ToolRegistry
from src.org.contracts import Claim, Evidence, Mission
from src.org.providers import ProviderConfig, ProviderPool
from src.org.sandbox import WorkspaceRunner, Worktree
from src.org.store import OrgStore
from src.org.verification import VerificationEngine


@pytest.fixture()
def store() -> OrgStore:
    return OrgStore(":memory:")


@pytest.fixture()
def mission(store: OrgStore) -> Mission:
    return store.create_mission(Mission(title="t", objective="o"))


@pytest.fixture()
def engine(store: OrgStore) -> VerificationEngine:
    runtime = AgentRuntime(ProviderPool([ProviderConfig()]), ToolRegistry(),
                           store)
    return VerificationEngine(runtime, store, WorkspaceRunner())


class TestClaimResolution:
    def test_fix_verified_by_replay(self, store: OrgStore,
                                    mission: Mission,
                                    engine: VerificationEngine) -> None:
        claim = store.add_claim(Claim(mission_id=mission.id,
                                      agent_role="dev:backend",
                                      statement="إصلاح", claim_kind="fix"))
        ev = store.add_evidence(Evidence(mission_id=mission.id, kind="replay",
                                         detail={"reproduced": True}, ok=True,
                                         claim_id=claim.id))
        resolved = engine.resolve_claim(claim, [ev])
        assert resolved.status == "verified"

    def test_red_test_cannot_use_green_baseline(
            self, store: OrgStore, mission: Mission,
            engine: VerificationEngine) -> None:
        """أساس أخضر (claim_id فارغ) لا يثبت ادعاء رقعة حمراء."""
        store.add_evidence(Evidence(mission_id=mission.id, kind="test_result",
                                    detail={"label": "baseline", "rc": 0},
                                    ok=True, claim_id=""))
        red_claim = store.add_claim(Claim(mission_id=mission.id,
                                          agent_role="qa:runner",
                                          statement="اختبار أحمر",
                                          claim_kind="test_pass"))
        resolved = engine.resolve_claim(red_claim, store.evidence_for(
            mission.id))
        assert resolved.status == "rejected"

    def test_failed_evidence_rejects_claim(self, store: OrgStore,
                                           mission: Mission,
                                           engine: VerificationEngine) -> None:
        claim = store.add_claim(Claim(mission_id=mission.id,
                                      agent_role="qa:runner",
                                      statement="اختبار نجح",
                                      claim_kind="test_pass"))
        store.add_evidence(Evidence(mission_id=mission.id, kind="test_result",
                                    detail={"rc": 1}, ok=False,
                                    claim_id=claim.id))
        resolved = engine.resolve_claim(claim, store.evidence_for(mission.id))
        assert resolved.status == "rejected"

    def test_no_evidence_rejected_not_pending(
            self, store: OrgStore, mission: Mission,
            engine: VerificationEngine) -> None:
        claim = store.add_claim(Claim(mission_id=mission.id,
                                      agent_role="dev:backend",
                                      statement="إصلاح", claim_kind="fix"))
        resolved = engine.resolve_claim(claim, [])
        assert resolved.status == "rejected"
        assert "غير مدعوم" in resolved.resolution

    def test_unknown_kind_rejected(self, engine: VerificationEngine) -> None:
        claim = Claim(mission_id="m", agent_role="x", statement="s",
                      claim_kind="rumor")
        with pytest.raises(ValueError, match="غير معلن"):
            engine.resolve_claim(claim, [])


class TestReproduce:
    def test_reproduce_links_evidence_to_claims(
            self, store: OrgStore, engine: VerificationEngine,
            tmp_path: Path) -> None:
        wt = Worktree.from_source(tmp_path, files=[])
        wt.write("tests/test_ok.py", "def test_ok():\n    assert 1 == 1\n")
        try:
            ok, evs = engine.reproduce_fix(mission := store.create_mission(
                Mission(title="t", objective="o")), wt,
                test_target="tests/test_ok.py", fix_claim_ids=["c1", "c2"])
            assert ok is True
            assert len(evs) == 2
            assert {e.claim_id for e in evs} == {"c1", "c2"}
        finally:
            wt.cleanup()

    def test_reproduce_failure_evidence_red(
            self, store: OrgStore, engine: VerificationEngine,
            tmp_path: Path) -> None:
        wt = Worktree.from_source(tmp_path, files=[])
        wt.write("tests/test_bad.py", "def test_bad():\n    assert 1 == 2\n")
        try:
            mission = store.create_mission(Mission(title="t", objective="o"))
            ok, evs = engine.reproduce_fix(mission, wt,
                                           test_target="tests/test_bad.py",
                                           fix_claim_ids=["c1"])
            assert ok is False and evs[0].ok is False
        finally:
            wt.cleanup()


class TestMissionVerification:
    def test_report_shape_and_audit(self, store: OrgStore,
                                    engine: VerificationEngine) -> None:
        mission = store.create_mission(Mission(title="t", objective="o"))
        claim = store.add_claim(Claim(mission_id=mission.id, agent_role="r",
                                      statement="ملاحظة موثقة",
                                      claim_kind="observation"))
        store.add_evidence(Evidence(mission_id=mission.id, kind="log",
                                    detail={"n": 1}, ok=True,
                                    claim_id=claim.id))
        report = engine.verify_mission(mission, store.claims_for(mission.id),
                                       [], None)
        assert report.verified >= 1
        assert report.rejected == 0
        actions = [r["action"] for r in store.tail_audit(10)]
        assert "verification.completed" in actions

    def test_fix_claim_without_worktree_rejected(
            self, store: OrgStore, engine: VerificationEngine) -> None:
        mission = store.create_mission(Mission(title="t", objective="o"))
        claim = store.add_claim(Claim(mission_id=mission.id,
                                      agent_role="dev:backend",
                                      statement="إصلاح بلا نسخة عمل",
                                      claim_kind="fix"))
        report = engine.verify_mission(mission, [claim], [], None)
        assert report.rejected >= 1
        assert report.reproduced_fix is False
