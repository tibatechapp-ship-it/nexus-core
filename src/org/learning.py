"""محرك الدروس — تعلّم مُتحكَّم لا يعدّل سياسة أمنية ولا يمنح صلاحية.

القواعد المعلنة:

* **الدرس يُستخرج من نتيجة موثّقة**: من مراجعات ونتائج فحص وحسم ادعاء —
  لا درس من نتيجة بلا سجل في المتجر.
* **الثقة من الأدلة**: درس مدعوم بدليل ناجح يرفع ثقته؛ درس من فشل
  يبدأ بثقة أقل — لا قفزات ثقة بلا إعادة إنتاج.
* **القراءة اقتراح لا أمر**: التخطيط يستقبل الدروس كنصوص مقترحة مرتبة
  بالثقة — لا واجهة هنا تعدّل سياسة أمنية أو تمنح صلاحية أو تغيّر
  بوابة دمج، وهذا مضمون بغياب أي دالة تكتب في سياسة أصلًا.
* **الأنماط المتكررة تُكتشف حتميًا**: تجميع نتائج الفحص بالفئة مع
  عتبة تكرار معلنة — نفس الفئة تتكرر = نمط معلن يستحق درسًا.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from src.org.contracts import Lesson
from src.org.store import OrgStore

__all__ = ["LessonsEngine"]

#: عتبة النمط المتكرر — فئة تتكرر بهذا العدد تصبح درسًا معلنًا.
PATTERN_THRESHOLD = 3

#: ثقة الدرس من نجاح موثّق ومن فشل — قيم معلنة لا تخمين.
CONFIDENCE_FROM_SUCCESS = 0.8
CONFIDENCE_FROM_FAILURE = 0.5


class LessonsEngine:
    """دروس التنظيم — تسجيل، كشف أنماط، قراءة مرتبة، عدّ تطبيق."""

    def __init__(self, store: OrgStore) -> None:
        self.store = store

    # ── التسجيل ───────────────────────────────────────────────────────────

    def record(self, text: str, scope: str, mission_id: str = "",
               from_success: bool = True) -> Lesson:
        """تسجيل درس واحد بثقة من مصدره — النص غير الفارغ شرط."""
        confidence = (CONFIDENCE_FROM_SUCCESS if from_success
                      else CONFIDENCE_FROM_FAILURE)
        return self.store.add_lesson(Lesson(
            text=text, scope=scope, confidence=confidence,
            source_mission_id=mission_id))

    def record_from_mission(self, mission_id: str) -> list[Lesson]:
        """استخراج دروس مهمة من سجلاتها — مراجعة/تحقق/فحص أمن."""
        lessons: list[Lesson] = []
        review_rows = self.store.reviews_for(mission_id)
        if review_rows:
            mean = sum(r.score for r in review_rows) // len(review_rows)
            lessons.append(self.record(
                f"متوسط مراجعة المهمة {mission_id} كان {mean} — "
                f"عدسات {sorted({r.lens for r in review_rows})}",
                scope="code_review", mission_id=mission_id,
                from_success=mean >= 80))
        findings = self.store.findings_for(mission_id)
        if findings:
            top = Counter(f.category for f in findings).most_common(1)[0]
            lessons.append(self.record(
                f"أكثر فئة نتائج في {mission_id}: {top[0]} ({top[1]} مرة)",
                scope="security" if any(f.source == "security"
                                        for f in findings) else "review",
                mission_id=mission_id, from_success=False))
        claims = self.store.claims_for(mission_id)
        verified = [c for c in claims if c.status == "verified"]
        if verified:
            lessons.append(self.record(
                f"{len(verified)} ادعاءً حققه التحقق في {mission_id}",
                scope="verification", mission_id=mission_id,
                from_success=True))
        rejected = [c for c in claims if c.status == "rejected"]
        if rejected:
            lessons.append(self.record(
                f"{len(rejected)} ادعاءً رفضه التحقق في {mission_id} — "
                "لا تصديق بلا أدلة",
                scope="verification", mission_id=mission_id,
                from_success=False))
        return lessons

    # ── كشف الأنماط المتكررة ──────────────────────────────────────────────

    def recurring_patterns(self) -> list[dict[str, Any]]:
        """أنماط نتائج متكررة عبر المهام — فئة ≥ عتبة معلنة."""
        counter: Counter[str] = Counter()
        for m in self.store.mission_list():
            for f in self.store.findings_for(m.id):
                counter[f.category] += 1
        return [
            {"category": cat, "count": n}
            for cat, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
            if n >= PATTERN_THRESHOLD
        ]

    # ── القراءة للتخطيط ───────────────────────────────────────────────────

    def lessons_for_planning(self, scope: str = "") -> list[str]:
        """نصوص دروس مقترحة للتخطيط — مرتبة بالثقة ثم التطبيق."""
        lessons = self.store.lessons_active()
        if scope:
            lessons = [lesson for lesson in lessons if lesson.scope == scope]
        return [lesson.text for lesson in lessons[:10]]

    def apply_lesson(self, lesson_id: str) -> None:
        """عدّ تطبيق درس — تتبع الاستخدام بلا تعديل نص أو ثقة."""
        self.store.lesson_bump(lesson_id)

    def planning_context(self, max_chars: int = 600) -> str:
        """سياق تخطيطي مضغوط من الدروس — حتمي ومقصوص بسقف معلن."""
        texts = self.lessons_for_planning()
        context = " \n".join(f"- {t}" for t in texts)
        if len(context) > max_chars:
            context = context[:max_chars].rsplit(" ", 1)[0] + "…"
        return context or "لا دروس نشطة بعد."

    def heartbeat(self) -> float:
        """طابع زمني للفحص الدوري — تتبع حيوية المحرك بلا حالة داخلية."""
        return time.time()
