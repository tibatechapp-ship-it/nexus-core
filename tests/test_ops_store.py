"""اختبارات المخزن الواحد — الجداول والهجرة وآلة الحالات والتدقيق.

القواعد المفروضة هنا هي قلب الطبقة: إزالة التكرار بالنافذة، انتقالات
الحالة القانونية فقط، الدمج بشرية+CI، فتح النشر قرار بشري، وسجل
التدقيق لا يفوّت قرارًا.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.ops.contracts import Digest, GateResult, Signal, Ticket, Verdict
from src.ops.store import OpsError, OpsStore, SCHEMA_VERSION


@pytest.fixture()
def store() -> OpsStore:
    """مخزن ذاكرة نظيف لكل اختبار — لا تلوث بين الحالات."""
    return OpsStore(":memory:")


class TestSchema:
    def test_schema_version_stamped(self, store: OpsStore) -> None:
        """رقم المخطط مختوم في meta — الهجرة من رقم واحد معروف."""
        row = store._conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        assert int(row["value"]) == SCHEMA_VERSION == 2

    def test_future_schema_rejected(self, tmp_path: object) -> None:
        """قاعدة أحدث من الكود رفع صريح — لا ترقية صامتة للأمام."""
        path = str(tmp_path) + "/fut.db"  # type: ignore[operator]
        raw = sqlite3.connect(path)
        raw.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        raw.execute("INSERT INTO meta VALUES ('schema_version', '999')")
        raw.commit()
        raw.close()
        with pytest.raises(OpsError, match="أحدث"):
            OpsStore(path)

    def test_counts_all_tables(self, store: OpsStore) -> None:
        """العدّ يغطي الجداول كلها صفرًا في البداية — اللوحة تبدأ صادقة."""
        counts = store.counts()
        assert counts == {
            "signals": 0, "verdicts": 0, "tickets": 0,
            "gates": 0, "digests": 0, "slices": 0,
        }


class TestSignals:
    def test_add_and_list_with_dedup(self, store: OpsStore) -> None:
        """نفس الرابط داخل النافذة يُهمَل — الإشارة الواحدة لا تتكرر."""
        s = Signal(source="pypi", title="x", url="https://pypi.org/a", score=3)
        assert store.add_signal(s) is True
        assert store.add_signal(s) is False
        listed = store.list_signals()
        assert len(listed) == 1 and listed[0].source == "pypi"

    def test_dedup_id_and_window_rules(self, store: OpsStore) -> None:
        """قواعد التكرار الثلاث: المعرّف إلزامي دائمًا، والنافذة تحكم
        الرابط المشترك بين مصادر مختلفة، وصفرها يعطّل فحص النافذة."""
        s = Signal(source="pypi", title="x", url="https://pypi.org/a")
        assert store.add_signal(s, dedup_window_days=0) is True
        # نفس المعرّف (نفس المصدر والرابط): إلزامي مهما كانت النافذة.
        assert store.add_signal(s, dedup_window_days=0) is False
        # نفس الرابط من مصدر آخر داخل نافذة 30 يومًا: مُهمَل.
        other = Signal(source="npm", title="x", url="https://pypi.org/a")
        assert store.add_signal(other, dedup_window_days=30) is False
        # نفس الرابط من مصدر آخر بنافذة صفر: مقبول — الفحص الزمني معطّل.
        assert store.add_signal(other, dedup_window_days=0) is True

    def test_day_filter_and_min_score(self, store: OpsStore) -> None:
        """الفلترة باليوم والدرجة الدنيا — عرض اللوحة يقرأ ما يعرضه فقط."""
        store.add_signal(Signal(source="a", title="hi", url="https://a/1",
                                score=5.0))
        store.add_signal(Signal(source="b", title="lo", url="https://b/1",
                                score=0.5))
        assert len(store.list_signals(min_score=1.0)) == 1
        assert store.list_signals(day="1999-01-01") == []

    def test_audit_written_on_signal(self, store: OpsStore) -> None:
        """كل إشارة مخزّنة لها سطر تدقيق — لا دخول بلا أثر."""
        store.add_signal(Signal(source="a", title="t", url="https://a/2"))
        actions = [e["action"] for e in store.tail_audit(10)]
        assert "signal.stored" in actions


class TestVerdicts:
    def test_add_and_latest(self, store: OpsStore) -> None:
        """آخر حكم لهدف يعود بالأدلة والفحوص كما خُزّنت."""
        v = Verdict(target="pkg@1", verdict="confirmed",
                    evidence=("دليل",), confidence=0.6,
                    checks={"static_scan": "finding"})
        store.add_verdict(v)
        latest = store.latest_verdict("pkg@1")
        assert latest is not None and latest.verdict == "confirmed"
        assert store.latest_verdict("nope@0") is None

    def test_upsert_updates_ticket_id(self, store: OpsStore) -> None:
        """إعادة تخزين نفس الحكم تحدّث التذكرة المرتبطة لا تكرر الصف."""
        v = Verdict(target="pkg@1", evidence=("دليل",), id="fixed-id")
        store.add_verdict(v)
        store.add_verdict(Verdict(target="pkg@1", evidence=("دليل",),
                                  id="fixed-id", ticket_id="T-1"))
        assert store.latest_verdict("pkg@1").ticket_id == "T-1"  # type: ignore[union-attr]
        assert store.counts()["verdicts"] == 1


class TestTicketLifecycle:
    def test_sequential_ids_and_branch(self, store: OpsStore) -> None:
        """المعرّفات تتصاعد سنويًا والفرع يُشتق — خط واحد لكل تذكرة."""
        t1 = store.add_ticket(Ticket(origin="radar", title="أولى"))
        t2 = store.add_ticket(Ticket(origin="webqa", title="ثانية"))
        assert t1.id == "T-2026-001" and t2.id == "T-2026-002"
        assert t1.branch == "t/T-2026-001"

    def test_full_legal_lifecycle_to_merged(self, store: OpsStore) -> None:
        """السلسلة الكاملة بالقواعد: وصول→تنفيذ→تقرير→مراجعة→دمج بشري+CI."""
        t = store.add_ticket(Ticket(origin="radar", title="دورة كاملة"))
        for nxt, actor, ci in (("branched", "agent", False),
                               ("executed", "agent", False),
                               ("reported", "agent", False),
                               ("reviewed", "human", False),
                               ("merged", "human", True)):
            t = store.ticket_advance(t.id, nxt, actor=actor, ci_green=ci)
        assert t.state == "merged"

    def test_agent_cannot_merge(self, store: OpsStore) -> None:
        """الوكيل لا يدمج مهما بلغت حالة المراجعة — بوابة بشرية صارمة."""
        t = store.add_ticket(Ticket(origin="radar", title="حجب وكيل"))
        for nxt in ("branched", "executed", "reported", "reviewed"):
            store.ticket_advance(t.id, nxt, actor="agent" if nxt != "reviewed" else "human")
        with pytest.raises(OpsError, match="بشرية"):
            store.ticket_advance(t.id, "merged", actor="agent", ci_green=True)

    def test_merge_requires_ci_green(self, store: OpsStore) -> None:
        """الدمج بلا CI أخضر مرفوض — بوابة لا مجاملة."""
        t = store.add_ticket(Ticket(origin="radar", title="حجب CI"))
        for nxt in ("branched", "executed", "reported", "reviewed"):
            store.ticket_advance(t.id, nxt,
                                 actor="agent" if nxt != "reviewed" else "human")
        with pytest.raises(OpsError, match="CI"):
            store.ticket_advance(t.id, "merged", actor="human", ci_green=False)

    def test_illegal_transition_rejected(self, store: OpsStore) -> None:
        """القفز خارج السلسلة رفع صريح — branched لا يدمج مباشرة."""
        t = store.add_ticket(Ticket(origin="radar", title="قفز"))
        store.ticket_advance(t.id, "branched")
        with pytest.raises(OpsError, match="غير قانوني"):
            store.ticket_advance(t.id, "merged", actor="human", ci_green=True)

    def test_unknown_state_and_missing_ticket(self, store: OpsStore) -> None:
        """حالة هدف غير معروفة وتذكرة غائبة خطأ صريح — لا تخمين."""
        t = store.add_ticket(Ticket(origin="radar", title="غ"))
        with pytest.raises(OpsError, match="غير معروفة"):
            store.ticket_advance(t.id, "teleported")
        with pytest.raises(OpsError, match="غير موجودة"):
            store.ticket_advance("T-9999-999", "closed")

    def test_publish_gate_rules(self, store: OpsStore) -> None:
        """فتح النشر: بشري فقط وبعد المراجعة — كل قاعدة مخالفة رفع."""
        t = store.add_ticket(Ticket(origin="radar", title="بوابة"))
        with pytest.raises(OpsError, match="بشري"):
            store.ticket_set_publish(t.id, True, actor="agent")
        with pytest.raises(OpsError, match="reviewed"):
            store.ticket_set_publish(t.id, True, actor="human")
        store.ticket_advance(t.id, "branched")
        store.ticket_advance(t.id, "executed")
        store.ticket_advance(t.id, "reported")
        store.ticket_advance(t.id, "reviewed", actor="human")
        updated = store.ticket_set_publish(t.id, True, actor="reviewer")
        assert updated.publish_allowed is True
        with pytest.raises(OpsError, match="غير موجودة"):
            store.ticket_set_publish("T-9-9", True, actor="human")

    def test_list_filter_and_state_counts(self, store: OpsStore) -> None:
        """الفلترة بالحالة وعدّ الحالات — قائمة تذاكر واحدة للوحة."""
        t = store.add_ticket(Ticket(origin="radar", title="أ"))
        store.add_ticket(Ticket(origin="radar", title="ب"))
        store.ticket_advance(t.id, "branched")
        assert len(store.ticket_list(state="branched")) == 1
        assert store.ticket_state_counts() == {"branched": 1, "open": 1}
        assert len(store.ticket_list()) == 2

    def test_stale_detection_and_auto_close(self, store: OpsStore) -> None:
        """الخوامل تُكتشف وتُغلق آليًا — النهائي لا يُمس."""
        t = store.add_ticket(Ticket(origin="radar", title="خاملة",
                                    created_at="2020-01-01T00:00:00+00:00",
                                    updated_at="2020-01-01T00:00:00+00:00"))
        assert [x.id for x in store.stale_tickets(days=14)] == [t.id]
        store.ticket_advance(t.id, "closed", actor="maintenance")
        assert store.stale_tickets(days=14) == []


class TestGates:
    def test_add_list_and_link_ticket(self, store: OpsStore) -> None:
        """البوابة تُخزَّن وتُربط تذكرتها لاحقًا — التحديث على السجل نفسه."""
        g = GateResult(tool="webqa", target="/tmp/x", blocking=True,
                       passed=False, findings=({"check": "html_validate"},))
        store.add_gate(g)
        store.gate_set_ticket(g.id, "T-2026-001")
        listed = store.list_gates(target="/tmp/x")
        assert listed[0].ticket_id == "T-2026-001"

    def test_link_missing_gate_rejected(self, store: OpsStore) -> None:
        """ربط تذكرة ببوابة غائبة خطأ صريح — لا ارتباطات خيالية."""
        with pytest.raises(OpsError, match="بوابة غير موجودة"):
            store.gate_set_ticket("no-id", "T-1")

    def test_list_gates_empty_target_filter(self, store: OpsStore) -> None:
        """فلترة هدف غير موجود تعود فارغة — استعلام صادق."""
        store.add_gate(GateResult(tool="webqa", target="/tmp/only"))
        assert store.list_gates(target="/nope") == []
        assert len(store.list_gates()) == 1


class TestDigestsAndAudit:
    def test_digest_upsert_per_day(self, store: OpsStore) -> None:
        """نفس النوع واليوم يستبدل السابق — ملخص واحد لا تراكم."""
        store.add_digest(Digest(kind="morning", day="2026-11-14",
                                payload={"n": 1}))
        store.add_digest(Digest(kind="morning", day="2026-11-14",
                                payload={"n": 2}))
        latest = store.latest_digest("morning")
        assert latest.payload["n"] == 2  # type: ignore[union-attr]
        assert store.counts()["digests"] == 1
        assert store.latest_digest("evening") is None
        assert store.latest_digest() is not None

    def test_audit_tail_and_details(self, store: OpsStore) -> None:
        """التدقيق يسجل الفاعل والتفاصيل — أحدث القرارات أولًا."""
        store.audit("x.done", "ref1", {"k": "v"}, actor="tester")
        entries = store.tail_audit(5)
        assert entries[0]["actor"] == "tester"
        assert entries[0]["details"] == {"k": "v"}
        assert entries[0]["ref"] == "ref1"
