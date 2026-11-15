"""اختبارات المقاييس والدروس — معدلات من السجلات ولا تعديل سياسات.

القواعد المفروضة: المقام الصفر يعطي 0.0، الدروس من نتائج موثّقة فقط،
والأنماط المتكررة تُكتشف بعتبة معلنة، ولا واجهة تمنح صلاحية.
"""

from __future__ import annotations

import pytest

from src.org.contracts import Claim, Evidence, Finding, Lesson, Mission, Review
from src.org.learning import PATTERN_THRESHOLD, LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.store import OrgStore


@pytest.fixture()
def store() -> OrgStore:
    return OrgStore(":memory:")


@pytest.fixture()
def populated(store: OrgStore) -> OrgStore:
    m1 = store.create_mission(Mission(title="أ", objective="o1"))
    m2 = store.create_mission(Mission(title="ب", objective="o2"))
    # المشي القانوني عبر الآلة ثم إعلان الإتمام
    from src.org.contracts import MISSION_PHASES
    cur = m1
    for phase in MISSION_PHASES[1:]:
        cur = store.mission_update(cur.with_phase(phase))
    store.mission_update(
        Mission(title=cur.title, objective=cur.objective, status="done",
                phase=cur.phase, id=cur.id))
    c1 = store.add_claim(Claim(mission_id=m1.id, agent_role="dev",
                               statement="إصلاح ناجح", claim_kind="fix"))
    ev = store.add_evidence(Evidence(mission_id=m1.id, kind="replay",
                                     detail={}, ok=True, claim_id=c1.id))
    store.claim_resolve(c1.id, "verified", "دليل", [ev.id])
    c2 = store.add_claim(Claim(mission_id=m2.id, agent_role="dev",
                               statement="إصلاح فاشل", claim_kind="fix"))
    store.claim_resolve(c2.id, "rejected", "بلا أدلة", [])
    store.mission_update(
        Mission(title=m2.title, objective=m2.objective, status="failed",
                phase=m2.phase, id=m2.id))
    # أوصاف متمايزة — المعرف الحتمي يجعل التكرار المطابق إدخالًا واحدًا
    for i in range(PATTERN_THRESHOLD):
        store.add_finding(Finding(mission_id=m1.id, source="security",
                                  category="injection", severity="high",
                                  description=f"إشارة حقن #{i}"))
    return store


class TestRates:
    def test_completion_rate_half(self, populated: OrgStore) -> None:
        metrics = OrgMetrics(populated)
        assert metrics.completion_rate() == 0.5

    def test_verified_fix_rate_half(self, populated: OrgStore) -> None:
        metrics = OrgMetrics(populated)
        assert metrics.verified_fix_rate() == 0.5

    def test_zero_denominator_safe(self, store: OrgStore) -> None:
        metrics = OrgMetrics(store)
        assert metrics.completion_rate() == 0.0
        assert metrics.verified_fix_rate() == 0.0
        assert metrics.agent_failure_rate() == 0.0

    def test_snapshot_records_metrics(self, populated: OrgStore) -> None:
        metrics = OrgMetrics(populated)
        snap = metrics.snapshot()
        assert "completion_rate" in snap
        stored = populated.metrics_snapshot()
        assert any(m["name"] == "org.completion_rate" for m in stored)


class TestUsage:
    def test_usage_totals(self, populated: OrgStore) -> None:
        m = populated.mission_list()[0]
        populated.add_agent_run(
            mission_id=m.id, task_id="t", role="dev:backend",
            provider="mock", model="mock-1", status="ok", attempts=1,
            tokens_in=100, tokens_out=50, cost_usd=0.0, latency_ms=1.5)
        usage = OrgMetrics(populated).usage_totals()
        assert usage["tokens_in"] == 100
        assert usage["agent_runs"] == 1
        assert usage["cost_per_task_usd"] == 0.0  # مزوّد محلي مجاني


class TestLessons:
    def test_record_confidence_by_source(self, store: OrgStore) -> None:
        engine = LessonsEngine(store)
        success = engine.record("درس نجاح", scope="qa", from_success=True)
        failure = engine.record("درس فشل", scope="qa", from_success=False)
        assert success.confidence > failure.confidence

    def test_lessons_from_mission(self, populated: OrgStore) -> None:
        engine = LessonsEngine(populated)
        m = populated.mission_list()[0]
        lessons = engine.record_from_mission(m.id)
        assert lessons  # مراجعة لا توجد لكن الادعاءات والنتائج توجد
        scopes = {lesson.scope for lesson in lessons}
        assert scopes <= {"code_review", "security", "review", "verification"}

    def test_recurring_patterns_threshold(self, populated: OrgStore) -> None:
        engine = LessonsEngine(populated)
        patterns = engine.recurring_patterns()
        assert patterns and patterns[0]["category"] == "injection"
        assert patterns[0]["count"] >= PATTERN_THRESHOLD

    def test_no_policy_or_permission_api(self, store: OrgStore) -> None:
        """التعلّم لا يعدّل سياسة أمنية ولا يمنح صلاحية — بلا واجهة أصلًا."""
        engine = LessonsEngine(store)
        public = [n for n in dir(engine) if not n.startswith("_")]
        forbidden = {"grant", "allow", "set_policy", "set_security",
                     "grant_permission", "relax", "approve_merge"}
        assert not forbidden & set(public)

    def test_planning_context_bounded(self, store: OrgStore) -> None:
        engine = LessonsEngine(store)
        for i in range(30):
            store.add_lesson(Lesson(text=f"درس رقم {i} " + "طويل " * 20,
                                    scope="qa", confidence=0.5))
        context = engine.planning_context(max_chars=200)
        assert len(context) <= 201

    def test_lesson_apply_bumps(self, store: OrgStore) -> None:
        engine = LessonsEngine(store)
        lesson = engine.record("درس قابل للتطبيق", scope="qa")
        engine.apply_lesson(lesson.id)
        rows = store.lessons_active()
        assert rows[0].applied_count == 1


class TestHonesty:
    def test_rejected_claims_reflected_in_rate(self, store: OrgStore) -> None:
        metrics = OrgMetrics(store)
        m = store.create_mission(Mission(title="t", objective="o"))
        c = store.add_claim(Claim(mission_id=m.id, agent_role="dev",
                                  statement="ادعاء بلا دليل", claim_kind="fix"))
        store.claim_resolve(c.id, "rejected", "بلا أدلة", [])
        assert metrics.verified_fix_rate() == 0.0

    def test_review_accuracy_zero_without_reviews(self, store: OrgStore) -> None:
        assert OrgMetrics(store).review_accuracy() == 0.0
