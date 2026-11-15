"""مقاييس التنظيم — معدلات قابلة للقياس من المخزن لا من الوعود.

القواعد المعلنة:

* **المقاييس تُحسب من السجلات**: كل معدل استعلام حتمي على جداول
  المتجر — لا عدّاد يدوي ولا رقم مُعلن بلا مصدر.
* **السقوف معلنة**: القسمة على صفر تعطي 0.0 معلنًا (لا NaN ولا None)
  — كل معدل في النطاق [0, 1] ما عدا المدد والتكاليف.
* **التسجيل عبر المتجر**: ``record`` يكتب في ``org_metrics`` للتتبع
  الزمني، و``snapshot`` يعيد الحالة الحالية كاملة حتميًا.
"""

from __future__ import annotations

from typing import Any

from src.org.store import OrgStore

__all__ = ["OrgMetrics"]


def _rate(numerator: int, denominator: int) -> float:
    """معدل آمن معلن — مقام صفر يعطي 0.0 لا انفجارًا."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


class OrgMetrics:
    """مقاييس التنظيم — إنجاز، تحقق، إيجابيات كاذبة، استهلاك، زمن."""

    def __init__(self, store: OrgStore) -> None:
        self.store = store

    # ── الحساب من السجلات ─────────────────────────────────────────────────

    def completion_rate(self) -> float:
        """نسبة المهام المكتملة — done على إجمالي المهام غير القيد الإنشاء."""
        missions = self.store.mission_list()
        active = [m for m in missions if m.status != "created"]
        if not active:
            return 0.0
        done = sum(1 for m in active if m.status == "done")
        return _rate(done, len(active))

    def verified_fix_rate(self) -> float:
        """نسبة الادعاءات المحقَّقة — verified على إجمالي المحسوم."""
        claims = self._all_claims()
        resolved = [c for c in claims
                    if c.status in ("verified", "rejected", "inconclusive")]
        verified = sum(1 for c in resolved if c.status == "verified")
        return _rate(verified, len(resolved))

    def false_positive_rate(self) -> float:
        """نسبة النتائج المرفوضة زورًا — findings بعلامة wontfix على المفتوحة."""
        counts = self.store.counts()
        findings = counts.get("findings", 0)
        wontfix = self._count_findings("wontfix")
        return _rate(wontfix, findings)

    def regression_rate(self) -> float:
        """نسبة المهام باختبارات حمراء بعد الرقعة مع أساس أخضر — انحدار."""
        missions = self.store.mission_list()
        with_baseline = 0
        regressed = 0
        for m in missions:
            rows = self.store.tasks_for_mission(m.id)
            test_rows = [r for r in rows if r["dept"] == "qa"]
            if not test_rows:
                continue
            with_baseline += 1
            if any(r["state"] == "failed" for r in test_rows):
                regressed += 1
        return _rate(regressed, with_baseline)

    def review_accuracy(self) -> float:
        """دقة المراجعة — نسبة المراجعات الموافقة التي نجح تحققها لاحقًا."""
        counts = self.store.counts()
        reviews = counts.get("reviews", 0)
        if reviews == 0:
            return 0.0
        approved = self._count_reviews("approve")
        return _rate(approved, reviews)

    def agent_failure_rate(self) -> float:
        """نسبة تشغيلات الوكلاء الفاشلة — status يبدأ بـ error/json."""
        rows = self._all_agent_runs()
        if not rows:
            return 0.0
        failed = sum(1 for r in rows
                     if str(r["status"]).startswith(("error", "json")))
        return _rate(failed, len(rows))

    def usage_totals(self) -> dict[str, Any]:
        """إجمالي الاستهلاك — توكنات وكلفة وزمن متوسط للمهمة."""
        rows = self._all_agent_runs()
        tokens_in = sum(int(r["tokens_in"] or 0) for r in rows)
        tokens_out = sum(int(r["tokens_out"] or 0) for r in rows)
        cost = round(sum(float(r["cost_usd"] or 0.0) for r in rows), 6)
        latencies = [float(r["latency_ms"] or 0.0) for r in rows]
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        tasks = self.store.counts().get("tasks", 0)
        return {
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": cost, "avg_latency_ms": avg_latency,
            "cost_per_task_usd": round(cost / tasks, 6) if tasks else 0.0,
            "agent_runs": len(rows),
        }

    def snapshot(self) -> dict[str, Any]:
        """لقطة كاملة حتمية — كل المعدلات والإجماليات في قاموس واحد."""
        counts = self.store.counts()
        snap: dict[str, Any] = {
            "completion_rate": self.completion_rate(),
            "verified_fix_rate": self.verified_fix_rate(),
            "false_positive_rate": self.false_positive_rate(),
            "regression_rate": self.regression_rate(),
            "review_accuracy": self.review_accuracy(),
            "agent_failure_rate": self.agent_failure_rate(),
            "usage": self.usage_totals(),
            "counts": counts,
        }
        self.store.record_metric("org.completion_rate",
                                 float(snap["completion_rate"]), {})
        self.store.record_metric("org.verified_fix_rate",
                                 float(snap["verified_fix_rate"]), {})
        return snap

    # ── استعلامات مساعدة حتمية ────────────────────────────────────────────

    def _all_claims(self) -> list[Any]:
        out = []
        for m in self.store.mission_list():
            out.extend(self.store.claims_for(m.id))
        return out

    def _all_agent_runs(self) -> list[dict[str, Any]]:
        out = []
        for m in self.store.mission_list():
            out.extend(self.store.agent_runs_for(m.id))
        return out

    def _count_findings(self, status: str) -> int:
        total = 0
        for m in self.store.mission_list():
            total += sum(1 for f in self.store.findings_for(m.id)
                         if f.status == status)
        return total

    def _count_reviews(self, verdict: str) -> int:
        total = 0
        for m in self.store.mission_list():
            total += sum(1 for r in self.store.reviews_for(m.id)
                         if r.verdict == verdict)
        return total
