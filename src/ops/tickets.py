"""خط التذاكر — كل حدث مؤثر يصير تذكرة بحالات محددة والنشر محجوب.

القواعد المعلنة المطبَّقة حرفيًا:

1. آلة الحالات مثبّتة في العقود: ``open → branched → executed →
   reported → reviewed → (merged | closed)`` — أي انتقال خارجها خطأ.
2. ``publish_allowed=False`` افتراضيًا؛ فتحه قرار بشري فقط، ويتطلّب
   حالة ``reviewed``/``merged`` — الوكيل لا يفتح النشر مهما بلغت صلاحياته.
3. الدمج يتطلّب مراجعة بشرية + CI أخضر — مفروضة في ``OpsStore`` قبل
   هنا، فالطبقتان تحملان القاعدة نفسها.
4. التذاكر الخاملة تُغلق تلقائيًا بعد مدة معلنة، مع سجل تدقيق كامل.

التنفيذ الجبري اختياري بالتصميم: ``ensure_branch`` ينشئ الفرع محليًا
عند توفر git، وغياب git يعني فرعًا مسمّى في التقرير فقط — الصدق
قبل الأتمتة.
"""

from __future__ import annotations

import subprocess
from typing import Any

from src.ops.contracts import FINAL_STATES, Ticket
from src.ops.store import OpsError, OpsStore

__all__ = ["TicketBoard", "REPORT_KEYS"]

#: مفاتيح التقرير الموحّد — الناقص يُملأ بقيمة صريحة لا بالصمت.
REPORT_KEYS: tuple[str, ...] = ("what", "why", "risk", "tests", "rollback")

#: مدة الخمول الافتراضية قبل الإغلاق التلقائي (أيام).
DEFAULT_STALE_DAYS = 14


class TicketBoard:
    """لوحة التذاكر — فتح، تقدّم، نشر، فرع، خاملة، إغلاق تلقائي."""

    def __init__(self, store: OpsStore) -> None:
        self._store = store

    # ── الفتح والتقدّم ────────────────────────────────────────────────────

    def open_ticket(self, origin: str, title: str,
                    report: dict[str, Any] | None = None) -> Ticket:
        """فتح تذكرة — التقرير الموحّد يُستكمل بمفاتيحه الصريحة دائمًا."""
        full_report = self._normalize_report(report)
        return self._store.add_ticket(
            Ticket(origin=origin, title=title, report=full_report)
        )

    def _normalize_report(self, report: dict[str, Any] | None) -> dict[str, Any]:
        """استكمال التقرير — كل مفتاح ناقص يصير «غير مذكور» لا غيابًا."""
        base: dict[str, Any] = dict(report or {})
        if "tests" in base and not isinstance(base["tests"], list):
            base["tests"] = [str(base["tests"])]
        for key in REPORT_KEYS:
            if key not in base:
                base[key] = "غير مذكور" if key != "tests" else []
        return base

    def advance(self, ticket_id: str, to_state: str, actor: str = "agent",
                ci_green: bool = False, note: str = "") -> Ticket:
        """تقدّم تذكرة — القواعد مفروضة في المخزن، وهنا الواجهة المعلنة."""
        return self._store.ticket_advance(
            ticket_id, to_state, actor=actor, ci_green=ci_green, note=note
        )

    # ── بوابة النشر ───────────────────────────────────────────────────────

    def allow_publish(self, ticket_id: str, actor: str) -> Ticket:
        """فتح بوابة النشر — قرار بشري بعد المراجعة، أو خطأ صريح."""
        return self._store.ticket_set_publish(ticket_id, True, actor=actor)

    def can_publish(self, ticket_id: str) -> bool:
        """هل النشر مسموح لهذه التذكرة؟ — سؤال الوكيل الوحيد قبل أي دمج."""
        t = self._store.ticket_get(ticket_id)
        return bool(t is not None and t.publish_allowed)

    # ── الفرع والتنفيذ ────────────────────────────────────────────────────

    def ensure_branch(self, ticket_id: str,
                      repo_path: str | None = None) -> dict[str, Any]:
        """فرع ``t/<id>`` — إنشاء محلي عند توفر git، وإلا اسم معلن فقط.

        العقد: العائد قاموس ``{branch, created, reason}`` — ``created``
        صادق دائمًا: ``False`` عند غياب git أو فشل الأمر، والسبب معلن.
        """
        t = self._store.ticket_get(ticket_id)
        if t is None:
            raise OpsError(f"تذكرة غير موجودة: {ticket_id}")
        branch = t.branch or f"t/{ticket_id}"
        if repo_path is None:
            return {"branch": branch, "created": False,
                    "reason": "تنفيذ جبري معطّل — فرع بالاسم في التقرير فقط"}
        try:
            subprocess.run(  # noqa: S603 — اسم الفرع مشتق من معرّف حتمي
                ["git", "checkout", "-b", branch],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            self._store.audit("ticket.branch_failed", ticket_id,
                              {"reason": str(exc)[:200]})
            return {"branch": branch, "created": False,
                    "reason": f"فشل إنشاء الفرع: {str(exc)[:120]}"}
        self._store.audit("ticket.branched", ticket_id, {"branch": branch})
        return {"branch": branch, "created": True, "reason": "تم إنشاء الفرع محليًا"}

    # ── الخمول والإغلاق ───────────────────────────────────────────────────

    def stale(self, days: int = DEFAULT_STALE_DAYS) -> list[Ticket]:
        """التذاكر الخاملة غير النهائية — مرشّحة للإغلاق التلقائي."""
        return self._store.stale_tickets(days)

    def auto_close_stale(self, days: int = DEFAULT_STALE_DAYS,
                         actor: str = "maintenance",
                         note: str = "إغلاق تلقائي — خمول عن المدة المعلنة") -> list[str]:
        """إغلاق الخوامل — النهائي لا يُمس، والمغلق له سجل تدقيق كامل."""
        closed: list[str] = []
        for t in self.stale(days):
            updated = self._store.ticket_advance(
                t.id, "closed", actor=actor, note=note
            )
            closed.append(updated.id)
        return closed

    def active(self) -> list[Ticket]:
        """التذاكر الناشطة — كل ما ليس ``merged``/``closed``."""
        return [t for t in self._store.ticket_list(limit=500)
                if t.state not in FINAL_STATES]
