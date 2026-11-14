"""اختبارات خط التذاكر — التقرير الموحّد والفرع والخمول والنوافذ النشطة."""

from __future__ import annotations

import pytest

from src.ops import OpsStore, OpsError
from src.ops.tickets import REPORT_KEYS, TicketBoard


@pytest.fixture()
def board() -> TicketBoard:
    """لوحة على مخزن ذاكرة — بلا آثار خارجية."""
    return TicketBoard(OpsStore(":memory:"))


class TestOpenTicket:
    def test_report_keys_normalized(self, board: TicketBoard) -> None:
        """التقرير يُستكمل بمفاتيحه الخمسة دائمًا — لا غياب ولا صمت."""
        t = board.open_ticket("radar", "مراجعة إشارة",
                              {"what": "حزمة جديدة", "why": "درجة عالية"})
        assert all(k in t.report for k in REPORT_KEYS)
        assert t.report["risk"] == "غير مذكور"
        assert t.report["tests"] == []
        assert t.report["rollback"] == "غير مذكور"

    def test_tests_coerced_to_list(self, board: TicketBoard) -> None:
        """قيمة tests غير قائمة تُحوَّل قائمة — العقد الموحّد محفوظ."""
        t = board.open_ticket("webqa", "فحص", {"tests": "unit"})
        assert t.report["tests"] == ["unit"]

    def test_publish_blocked_by_default(self, board: TicketBoard) -> None:
        """النشر محجوب افتراضيًا — القاعدة الافتتاحية للطبقة كلها."""
        t = board.open_ticket("sandbox", "حكم عزل")
        assert t.publish_allowed is False and t.state == "open"
        assert t.branch == f"t/{t.id}"


class TestAdvanceAndPublish:
    def test_lifecycle_with_publish_gate(self, board: TicketBoard) -> None:
        """الدورة الكاملة: نشر يُفتح بعد المراجعة فقط وبقرار بشري."""
        t = board.open_ticket("radar", "دورة")
        for nxt in ("branched", "executed", "reported"):
            t = board.advance(t.id, nxt)
        t = board.advance(t.id, "reviewed", actor="human")
        assert not board.can_publish(t.id)
        t = board.allow_publish(t.id, actor="reviewer")
        assert board.can_publish(t.id) and t.publish_allowed

    def test_agent_cannot_open_publish(self, board: TicketBoard) -> None:
        """الوكيل لا يفتح النشر — المحاولة رفع صريح."""
        t = board.open_ticket("radar", "حجب")
        with pytest.raises(OpsError, match="بشري"):
            board.allow_publish(t.id, actor="agent")

    def test_ensure_branch_off_by_default(self, board: TicketBoard) -> None:
        """بلا مسار مستودع: الفرع بالاسم في التقرير فقط — صدق قبل أتمتة."""
        t = board.open_ticket("radar", "فرع منطقي")
        result = board.ensure_branch(t.id)
        assert result["branch"] == t.branch
        assert result["created"] is False

    def test_ensure_branch_with_repo(self, board: TicketBoard,
                                     tmp_path: object) -> None:
        """مع مستودع حقيقي: الفرع يُنشأ محليًا ويُسجل في التدقيق."""
        import subprocess
        repo = str(tmp_path)  # type: ignore[operator]
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@x", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=repo, check=True,
        )
        t = board.open_ticket("radar", "فرع فعلي")
        result = board.ensure_branch(t.id, repo_path=repo)
        assert result["created"] is True
        heads = subprocess.run(["git", "branch", "--list", t.branch],
                               cwd=repo, capture_output=True, text=True)
        assert t.branch in heads.stdout

    def test_ensure_branch_missing_ticket(self, board: TicketBoard) -> None:
        """فرع لتذكرة غائبة رفع — لا أعمال على خيال."""
        with pytest.raises(OpsError, match="غير موجودة"):
            board.ensure_branch("T-9999-999")

    def test_ensure_branch_fails_gracefully(self, board: TicketBoard) -> None:
        """فشل git يُلتقط في النتيجة — السبب معلن لا استثناء متطاير."""
        t = board.open_ticket("radar", "فرع فاشل")
        result = board.ensure_branch(t.id, repo_path="/nonexistent/repo")
        assert result["created"] is False and "فشل" in result["reason"]


class TestStaleAndActive:
    def test_auto_close_stale_only_active(self, board: TicketBoard) -> None:
        """الإغلاق الآلي يمس الخوامل النشطة فقط — النهائي لا يُمس."""
        stale_t = board.open_ticket("radar", "خاملة")
        fresh_t = board.open_ticket("radar", "نشطة")
        board._store._conn.execute(
            "UPDATE tickets SET updated_at = '2020-01-01T00:00:00+00:00' "
            "WHERE id = ?", (stale_t.id,)
        )
        closed = board.auto_close_stale(days=14, actor="maintenance")
        assert closed == [stale_t.id]
        assert board._store.ticket_get(stale_t.id).state == "closed"  # type: ignore[union-attr]
        assert board._store.ticket_get(fresh_t.id).state == "open"  # type: ignore[union-attr]

    def test_active_excludes_final(self, board: TicketBoard) -> None:
        """الناشطة لا تحسب المدموجة والمغلقة — قائمة العمل تظل صادقة."""
        t = board.open_ticket("radar", "تُغلق")
        board.advance(t.id, "closed")
        board.open_ticket("radar", "تبقى")
        active = board.active()
        assert len(active) == 1 and active[0].state == "open"

    def test_stale_listing(self, board: TicketBoard) -> None:
        """قائمة الخوامل تعود بالتذاكر الخاملة نفسها."""
        t = board.open_ticket("radar", "قديمة")
        board._store._conn.execute(
            "UPDATE tickets SET updated_at = '2020-01-01T00:00:00+00:00' "
            "WHERE id = ?", (t.id,)
        )
        assert [x.id for x in board.stale(14)] == [t.id]
