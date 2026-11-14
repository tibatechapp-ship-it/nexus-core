"""اللوحة الواحدة — لقطة عدّية وتقرير Markdown حتمي وملخص دورة موحّد.

القاعدة المعلنة: **لوحة تحكم واحدة وقائمة تذاكر واحدة** — كل المكوّنات
تكتب في المخزن الواحد، واللوحة تقرأه ولا تعرف شيئًا عن تفاصيل
المكوّنات؛ ما يجعل إضافة مكوّن لا تعدّل اللوحة.

الحتمية: نفس المخزن يعطي نفس نص التقرير حرفيًا — لا طوابع زمنية في
المتن، والترتيب ثابت، والأعداد مقروءة من استعلامات ثابتة. هذا يجعل
التقرير قابلاً للاختبار بالمقارنة النصية المباشرة، وهو أساس بوابة
«التقرير المجدد في CI» المعتمدة في هذا المستودع.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.ops.contracts import Digest
from src.ops.store import OpsStore

__all__ = ["OpsDashboard"]

#: ترتيب حالات التذكرة في العرض — ثابت معلن لا ترتيب استعلامي متقلب.
STATE_ORDER: tuple[str, ...] = (
    "open", "branched", "executed", "reported", "reviewed", "merged", "closed",
)


class OpsDashboard:
    """اللوحة الموحّدة — لقطة، تقرير نصي حتمي، كتابة ملفات، ملخص دورة."""

    def __init__(self, store: OpsStore,
                 outdir: str | Path = "reports/ops") -> None:
        self._store = store
        self._outdir = Path(outdir)

    # ── اللقطة العدّية ────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """لقطة واحدة من المخزن — أساس التقرير والملخص والعرض الواحد."""
        counts = self._store.counts()
        digest = self._store.latest_digest()
        gates = self._store.list_gates(limit=5)
        all_gates = self._store.list_gates(limit=200)
        return {
            "counts": counts,
            "ticket_states": self._store.ticket_state_counts(),
            "latest_digest": digest.to_dict() if digest else None,
            "recent_gates": [g.to_dict() for g in gates],
            "failed_gates_total": sum(1 for g in all_gates if not g.passed),
        }

    # ── التقرير الحتمي ────────────────────────────────────────────────────

    def render_markdown(self) -> str:
        """تقرير لوحة واحد — حتمي النص، ثابت الترتيب، بلا طوابع زمنية."""
        snap = self.snapshot()
        c = snap["counts"]
        states = snap["ticket_states"]
        lines: list[str] = [
            "# لوحة الطبقة التشغيلية الداخلية",
            "",
            "## العدّ الكلي",
            "",
            f"- إشارات الرادار: {c['signals']}",
            f"- أحكام العزل: {c['verdicts']}",
            f"- التذاكر: {c['tickets']}",
            f"- بوابات الفحص: {c['gates']}",
            f"- الملخصات: {c['digests']}",
            f"- شرائح الفهرس: {c['slices']}",
            "",
            "## خط التذاكر بالحالات",
            "",
        ]
        for state in STATE_ORDER:
            n = states.get(state, 0)
            if n:
                lines.append(f"- {state}: {n}")
        if not any(states.values()):
            lines.append("- لا تذاكر بعد")
        lines.extend(["", "## آخر ملخص", ""])
        latest = snap["latest_digest"]
        if latest:
            lines.append(f"- النوع: {latest['kind']} · اليوم: {latest['day']}")
            summary = str(latest["payload"].get("summary", "")).strip()
            for row in summary.splitlines()[:6]:
                lines.append(f"  {row}")
        else:
            lines.append("- لا ملخصات بعد")
        lines.extend(["", "## البوابات الأخيرة", ""])
        if snap["recent_gates"]:
            for g in snap["recent_gates"]:
                verdict = "نجحت" if g["passed"] else "فشلت"
                kind = "حاجبة" if g["blocking"] else "استشارية"
                lines.append(
                    f"- [{g['tool']}] {Path(g['target']).name} — {verdict} ({kind}) "
                    f"نتائج={len(g['findings'])}"
                )
        else:
            lines.append("- لا بوابات بعد")
        lines.append("")
        return "\n".join(lines)

    # ── الكتابة ───────────────────────────────────────────────────────────

    def write(self) -> dict[str, Path]:
        """كتابة التقرير واللقطة — ملفان ثابتا الاسم يعادان كل دورة."""
        self._outdir.mkdir(parents=True, exist_ok=True)
        md = self._outdir / "dashboard.md"
        js = self._outdir / "dashboard.json"
        md.write_text(self.render_markdown(), encoding="utf-8")
        js.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {"markdown": md, "json": js}

    # ── ملخص الدورة ───────────────────────────────────────────────────────

    def build_cycle_digest(self, extras: dict[str, Any] | None = None) -> Digest:
        """ملخص دورة واحد — أعلى الإشارات وحالة التذاكر في نص واحد حتمي."""
        snap = self.snapshot()
        top = self._store.list_signals(limit=3)
        lines = [
            f"الإشارات: {snap['counts']['signals']} · التذاكر: "
            f"{snap['counts']['tickets']} · البوابات الفاشلة: "
            f"{snap['failed_gates_total']}",
        ]
        for s in top:
            lines.append(f"- [{s.score:.1f}] {s.source}: {s.title}")
        payload: dict[str, Any] = {
            "summary": "\n".join(lines),
            "snapshot": snap,
            "extras": extras or {},
            "counts": snap["counts"],
        }
        digest = Digest(
            kind="cycle", day=time.strftime("%Y-%m-%d"), payload=payload
        )
        return self._store.add_digest(digest)
