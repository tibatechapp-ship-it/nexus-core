"""اختبارات مجلس المراجعة — استقلال، إجماع، حجب، نقاش.

القواعد المفروضة: لا مراجع يراجع دوره نفسه، قضية حرجة تحجب مهما كان
المتوسط، لا توافق بلا مراجعات، وفشل مراجع = طلب تغييرات لا توافق صامت.
"""

from __future__ import annotations

import pytest

from src.org.agents import AgentRuntime, ToolRegistry
from src.org.contracts import Mission, Review
from src.org.providers import ProviderConfig, ProviderPool
from src.org.review import CouncilDecision, ReviewCouncil
from src.org.store import OrgStore


@pytest.fixture()
def store() -> OrgStore:
    return OrgStore(":memory:")


@pytest.fixture()
def mission(store: OrgStore) -> Mission:
    return store.create_mission(Mission(title="t", objective="o"))


@pytest.fixture()
def council(store: OrgStore) -> ReviewCouncil:
    runtime = AgentRuntime(ProviderPool([ProviderConfig()]), ToolRegistry(),
                           store)
    return ReviewCouncil(runtime, store)


class TestConsensus:
    def test_all_approve_passes(self, store: OrgStore, mission: Mission,
                                council: ReviewCouncil) -> None:
        reviews = [
            Review(mission_id=mission.id, task_id="t1",
                   reviewer=f"review:{lens}", lens=lens,
                   verdict="approve", score=90)
            for lens in ("logic", "security")
        ]
        decision = council.decide(mission.id, "t1", reviews)
        assert decision.verdict == "approve"
        assert decision.mean_score == 90
        assert store.reviews_for(mission.id)  # محفوظة

    def test_low_mean_blocks(self, store: OrgStore, mission: Mission,
                             council: ReviewCouncil) -> None:
        reviews = [
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:logic", lens="logic",
                   verdict="approve", score=60),
        ]
        decision = council.decide(mission.id, "t1", reviews)
        assert decision.verdict == "request_changes"
        assert any("عتبة" in r for r in decision.reasons)

    def test_critical_issue_blocks_regardless_of_mean(
            self, store: OrgStore, mission: Mission,
            council: ReviewCouncil) -> None:
        reviews = [
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:security", lens="security",
                   verdict="approve", score=95,
                   issues=[{"severity": "critical", "file": "x.py",
                            "line": 3, "message": "تنفيذ ديناميكي"}]),
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:logic", lens="logic",
                   verdict="approve", score=95),
        ]
        decision = council.decide(mission.id, "t1", reviews)
        assert decision.verdict == "request_changes"
        assert any("تنفيذ ديناميكي" in r for r in decision.reasons)

    def test_no_reviews_means_no_consent(
            self, store: OrgStore, mission: Mission,
            council: ReviewCouncil) -> None:
        decision = council.decide(mission.id, "t1", [])
        assert decision.verdict == "request_changes"
        assert "لا مراجعات" in decision.reasons[0]


class TestIndependence:
    def test_dev_role_skipped(self, store: OrgStore, mission: Mission,
                              council: ReviewCouncil) -> None:
        """مراجع لا يوافق على تعديله هو — دور المطوّر يُستبعد."""
        reviews = council.collect(mission.id, "t1", dev_role="review:logic",
                                  diff_text="- x = 1\n", notes="")
        assert all(r.lens != "logic" for r in reviews)

    def test_reviewer_failure_is_request_changes(
            self, store: OrgStore, mission: Mission,
            council: ReviewCouncil) -> None:
        """مراجع فاشل لا يمنح توافقًا صامتًا."""
        from src.org.providers import ProviderError

        class BoomPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise ProviderError("مزوّد ميت")

        council.runtime.pool = BoomPool()  # type: ignore[assignment]
        reviews = council.collect(mission.id, "t1", dev_role="dev:backend",
                                  diff_text="- x = 1\n", notes="")
        assert reviews
        assert all(r.verdict == "request_changes" for r in reviews)
        assert all(r.score == 0 for r in reviews)


class TestDebate:
    def test_debate_round_recorded(
            self, store: OrgStore, mission: Mission,
            council: ReviewCouncil) -> None:
        """الخلاف يُعاد بجولة ثانية مسجّلة بدورة 2."""
        reviews = [
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:logic", lens="logic",
                   verdict="request_changes", score=60,
                   comments="حارس ناقص"),
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:security", lens="security",
                   verdict="approve", score=90),
        ]
        decision = council.decide(mission.id, "t1", reviews)
        assert decision.dissent == ["logic"]
        decision2, _ = council.review_with_debate(
            mission.id, "t1", dev_role="dev:backend", diff_text="- x = 1\n",
            max_rounds=2)
        assert decision2.rounds >= 1

    def test_decision_deterministic(self, store: OrgStore,
                                    mission: Mission) -> None:
        reviews = [
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:logic", lens="logic",
                   verdict="approve", score=88),
            Review(mission_id=mission.id, task_id="t1",
                   reviewer="review:security", lens="security",
                   verdict="approve", score=84),
        ]
        runtime = AgentRuntime(ProviderPool([ProviderConfig()]),
                               ToolRegistry(), store)
        c1 = ReviewCouncil(runtime, store).decide(mission.id, "t1", reviews)
        c2 = ReviewCouncil(runtime, store).decide(mission.id, "t1", reviews)
        assert (c1.verdict, c1.mean_score) == (c2.verdict, c2.mean_score)


class TestCouncilDecisionShape:
    def test_decision_fields(self) -> None:
        d = CouncilDecision(verdict="approve", mean_score=85)
        assert d.rounds == 1 and d.reasons == []
