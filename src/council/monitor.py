"""Council Monitor — دور المجلس الدائم: مراقبة وتقييم الوكلاء (ب1.4).

خطة التناغم (``docs/harmony-plan.md`` الموجة 1): المجلس لا يُستشار
استباقياً؛ يُستدعى عند العجز (تصعيد المحرك — ``src.coder.engine``) أو
بالطلب، **ودوره الدائم مراقبة وتقييم الوكلاء** من سجل الأثر المعياري
(``runs/trace.jsonl`` — حقوله الإلزامية: ts/agent/tool/duration_ms/outcome).

الوحدة قراءة-فقط بحتة: لا شبكة، لا LLM، لا كتابة — حاكم حتمي نقي وفق
طبقة الشكل (``docs/FORMAL_REFERENCE.md``): الحكم يُشتق من الأرقام بقواعد
معلنة لا من انطباع نموذج. غياب السجل أو فساده ⇒ ``{}`` معلن — بلا قياس
لا تقييم ولا انفجار.

القواعد المعلنة (للجميع وللفاحص):
* معدل النجاح ≥ 0.95 وعدد التشغيلات ≥ 5 ⇒ ``monitor-clear`` (مراقبة مستمرة).
* معدل النجاح ≥ 0.8 ⇒ ``watch`` (مراقبة مكثفة).
* أقل من ذلك ⇒ ``council-review`` (تدخل المجلس: إعادة تعليم أو عزل).
* أقل من 5 تشغيلات ⇒ ``insufficient-data`` (لا حكم قبل الدليل الكافي).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["evaluate_agents", "council_verdict", "summary", "default_trace_path"]

ROOT = Path(__file__).resolve().parents[2]

#: عتبات الحكم الحتمي — معلنة للفاحص وللعرض في الواجهة.
WATCH_RATE = 0.80
CLEAR_RATE = 0.95
CLEAR_MIN_RUNS = 5

#: أسماء الأحكام الثلاثة + حالة البيئة الناقصة (إنجليزية لثبات العقد).
VERDICT_CLEAR = "monitor-clear"
VERDICT_WATCH = "watch"
VERDICT_REVIEW = "council-review"
VERDICT_INSUFFICIENT = "insufficient-data"


def default_trace_path() -> Path:
    """مسار سجل الأثر المعتمد — احترام متغير البيئة نفسه الذي يكتبه."""
    env = Path(__file__).resolve().parents[2] / "runs" / "trace.jsonl"
    import os

    override = os.environ.get("NEXUS_TRACE_PATH")
    return Path(override) if override else env


def _rows(path: Path) -> list[dict[str, Any]]:
    """اقرأ أسطر الأثر الصالحة — السطر الفاسد يُسقط صامتاً (best-effort)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and {"agent", "outcome"} <= set(row):
            rows.append(row)
    return rows


def evaluate_agents(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """تقييم حتمي لكل وكيل ظهر في سجل الأثر.

    الإرجاع: ``{agent: stats}`` حيث stats يحمل:
    ``runs`` (عدد الأحداث)، ``ok``/``fail``، ``success_rate`` (بدقة منزلتين)،
    ``avg_ms`` (متوسط المدة)، ``last_outcome``، ``grade`` (الحكم الحتمي).
    غياب السجل أو فساده ⇒ ``{}`` معلن.
    """
    rows = _rows(Path(path) if path is not None else default_trace_path())
    if not rows:
        return {}
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent = str(row.get("agent", ""))
        if not agent:
            continue
        st = stats.setdefault(agent, {
            "runs": 0, "ok": 0, "fail": 0, "total_ms": 0.0, "last_outcome": "",
        })
        st["runs"] += 1
        outcome = str(row.get("outcome", ""))
        if outcome == "ok":
            st["ok"] += 1
        else:
            st["fail"] += 1
        st["last_outcome"] = outcome
        try:
            st["total_ms"] += float(row.get("duration_ms", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass  # مدة فاسدة لا تُسقط الحدث كله
    result: dict[str, dict[str, Any]] = {}
    for agent, st in stats.items():
        runs = st.pop("runs")
        rate = round(st["ok"] / runs, 2) if runs else 0.0
        avg = round(st.pop("total_ms") / runs, 2) if runs else 0.0
        entry = {
            "runs": runs,
            "ok": st["ok"],
            "fail": st["fail"],
            "success_rate": rate,
            "avg_ms": avg,
            "last_outcome": st["last_outcome"],
            "grade": _grade(rate, runs),
        }
        entry["verdict"] = council_verdict(entry)
        result[agent] = entry
    return result


def _grade(rate: float, runs: int) -> str:
    """الحكم الحتمي من الأرقام — القواعد المعلنة في رأس الوحدة."""
    if runs < CLEAR_MIN_RUNS:
        return VERDICT_INSUFFICIENT
    if rate >= CLEAR_RATE:
        return VERDICT_CLEAR
    if rate >= WATCH_RATE:
        return VERDICT_WATCH
    return VERDICT_REVIEW


def council_verdict(entry: dict[str, Any]) -> dict[str, str]:
    """قرار المجلس المشتق من التقييم — حتمي نقي، بلا استثناءات.

    الإرجاع: ``{"action", "reason"}`` — الإجراء بالعربية للعرض، والسبب
    يحمل الأرقام التي أنتجته (صدق بيئي: الحكم يظهر دليله).
    """
    grade = entry.get("grade", VERDICT_INSUFFICIENT)
    rate = entry.get("success_rate", 0.0)
    runs = entry.get("runs", 0)
    if grade == VERDICT_REVIEW:
        return {
            "action": "تدخل المجلس: إعادة تعليم أو عزل مؤقت",
            "reason": f"success_rate={rate} على {runs} تشغيلاً تحت عتبة {WATCH_RATE}",
        }
    if grade == VERDICT_WATCH:
        return {
            "action": "مراقبة مكثفة: يبقى في الخدمة بلا ترقية",
            "reason": f"success_rate={rate} على {runs} تشغيلاً بين {WATCH_RATE} و{CLEAR_RATE}",
        }
    if grade == VERDICT_CLEAR:
        return {
            "action": "مراقبة مستمرة: أداء سليم",
            "reason": f"success_rate={rate} على {runs} تشغيلاً ≥ {CLEAR_RATE}",
        }
    return {
        "action": "لا حكم بعد: البيئة الناقصة تُعلن لا تُخمَّن",
        "reason": f"runs={runs} < {CLEAR_MIN_RUNS} — لا يُحكم قبل الدليل الكافي",
    }


def summary(evaluations: dict[str, dict[str, Any]]) -> dict[str, int]:
    """ملخّص الأحكام — عدّاد لكل درجة، للعرض الحي في الواجهة."""
    counts = {VERDICT_CLEAR: 0, VERDICT_WATCH: 0, VERDICT_REVIEW: 0,
              VERDICT_INSUFFICIENT: 0}
    for entry in evaluations.values():
        grade = entry.get("grade", VERDICT_INSUFFICIENT)
        counts[grade] = counts.get(grade, 0) + 1
    return counts
