"""Fleet Benchmark — قياس أداء الأسطول وترتيبه.

الفلسفة: **لا نقيس ما لا يمكن قياسه بأمان أوفلاين.** القياسات المعلنة:

* ``import_ms`` — زمن استيراد الوحدة (ساخن: خدمة طويلة العمر هي الحالة
  الإنتاجية الأصلية، فالسخانة هي الرقم الذي يؤثر على التوجيه الفعلي).
* ``entrypoint`` — هل رمز الدخول حاضر وقابل للاستدعاء (وزنه جزء من الدرجة
  لا جزء من الزمن).
* ``run_ms`` — وكلاء core وحدهم: استدعاء فعلي لمهمة واحدة فوق خادم زائف
  صامت (عقد ``run`` يضمن عدم رفع استثناءات، فالقياس آمن ومحدود).

الدرجة 0–100 = صحة 50٪ + سرعة استيراد 25٪ + اكتمال دخول 25٪، والطبقات
S/A/B/C عتباتها معلنة. الترتيب مستقر حتمياً: الدرجة ثم الاسم.
"""

from __future__ import annotations

import time

from src.fleet.conformance import SilentBackend, ensure_src_on_path
from src.fleet.record import AgentRecord

__all__ = ["benchmark", "rank", "tier_of", "SCORE_WEIGHTS", "TIER_THRESHOLDS"]

#: أوزان مكونات الدرجة — مجموعها 1.0 ومعلنة لتُناقش لا لتُخمَّن.
SCORE_WEIGHTS = {"health": 0.5, "speed": 0.25, "entry": 0.25}

#: عتبات الطبقات (>=): S ممتاز، A جيد، B مقبول، C بحاجة عمل.
TIER_THRESHOLDS = {"S": 95.0, "A": 85.0, "B": 70.0}

#: سقف زمن استيراد «مقبول» بالمللي ثانية — فوقه يتناقص مكوّن السرعة خطياً.
SPEED_CAP_MS = 50.0


def tier_of(score: float) -> str:
    """طبقة الدرجة: S ≥ 95، A ≥ 85، B ≥ 70، C ما دون."""
    for name, threshold in TIER_THRESHOLDS.items():
        if score >= threshold:
            return name
    return "C"


def _speed_component(import_ms: float) -> float:
    """100 للاستيراد الفوري حتى 0 عند ``SPEED_CAP_MS`` وما فوق (خطي)."""
    if import_ms <= 1.0:
        return 100.0
    if import_ms >= SPEED_CAP_MS:
        return 0.0
    return round(100.0 * (SPEED_CAP_MS - import_ms) / (SPEED_CAP_MS - 1.0), 2)


def benchmark(records: list[AgentRecord], *, deep: bool = False) -> list[dict]:
    """قياس كل وكيل وإرجاع نتائجه بلا ترتيب (الترتيب عمل ``rank``)."""
    ensure_src_on_path()
    results: list[dict] = []
    for rec in records:
        started = time.perf_counter()
        entry_ok = False
        run_ms: float | None = None
        import_ok = True
        try:
            import importlib

            module = importlib.import_module(rec.module)
            entry = getattr(module, rec.symbol, None)
            entry_ok = entry is not None
            if deep and rec.framework == "core" and entry_ok:
                agent = entry(SilentBackend())  # type: ignore[misc]
                t0 = time.perf_counter()
                agent.run("benchmark ping")
                run_ms = round((time.perf_counter() - t0) * 1000, 2)
        except Exception:  # noqa: BLE001 — الوكيل المكسور يُقاس بصحة 0
            import_ok = False
        import_ms = round((time.perf_counter() - started) * 1000, 2)
        results.append({
            "name": rec.name,
            "framework": rec.framework,
            "import_ms": import_ms,
            "import_ok": import_ok,
            "entrypoint_ok": entry_ok,
            "run_ms": run_ms,
        })
    return results


def rank(records: list[AgentRecord], conformance: dict, bench: list[dict]) -> list[dict]:
    """دمج الصحة والقياس في درجة 0–100 وترتيب نهائي بطبقات.

    ``conformance`` ناتج ``run_conformance`` و``bench`` ناتج ``benchmark``
    على نفس الأسطول — الوكيل المفقود من أيهما يُعامل أسوأ حالة عدلاً.
    """
    health = {r["name"]: r["status"] for r in conformance.get("reports", [])}
    health_score = {"healthy": 100.0, "degraded": 60.0, "broken": 0.0}
    bench_by_name = {b["name"]: b for b in bench}

    ranked: list[dict] = []
    for rec in records:
        status = health.get(rec.name, "broken")
        b = bench_by_name.get(rec.name)
        import_ms = b["import_ms"] if b else SPEED_CAP_MS
        speed = _speed_component(import_ms) if (b and b["import_ok"]) else 0.0
        entry = 100.0 if (b and b["entrypoint_ok"]) else 0.0
        score = round(
            SCORE_WEIGHTS["health"] * health_score[status]
            + SCORE_WEIGHTS["speed"] * speed
            + SCORE_WEIGHTS["entry"] * entry,
            2,
        )
        ranked.append({
            "rank": 0,
            "name": rec.name,
            "framework": rec.framework,
            "category": rec.category,
            "criticality": rec.criticality,
            "status": status,
            "import_ms": import_ms,
            "run_ms": (b or {}).get("run_ms"),
            "score": score,
            "tier": tier_of(score),
        })
    ranked.sort(key=lambda r: (-r["score"], r["name"]))
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked
