"""Fleet Benchmark — قياس أداء الأسطول وترتيبه.

الفلسفة: **لا نقيس ما لا يمكن قياسه بأمان أوفلاين، ومن لا يُقاس لا يُمنح
نقاط استدعاء.** القياسات المعلنة (كلها ``mode: "fake-clock"`` — بلا شبكة
وبلا LLM حقيقي):

* ``import_ms`` — زمن استيراد الوحدة (ساخن: خط التقارير يستوردها في فحص
  المطابقة قبل القياس، فالمقيس هو الزمن الساخن الذي يؤثر على التوجيه).
* ``entrypoint`` — هل رمز الدخول حاضر وقابل للاستدعاء.
* ``run_ms`` — الاستدعاء المحدود: وكلاء core فوق خادم صامت (عقد ``run``
  يضمن عدم رفع استثناءات)، ووكلاء novamind عبر حِمل ``src.fleet.probe``
  (بناء أوفلاين + استدعاء فوق سلّم مدخلات حميدة معلن). ``run_kind`` يعلن
  ماذا قيس: ``invoke`` (استدعاء فعلي) أو ``construct`` (بناء فقط لوكلاء
  بلا عقد استدعاء) — ومكوّن SLO يُحسب على ``invoke`` وحده لا على البناء.

**نموذج الدرجة (ب1.3 — v1.49.0):** الدرجة 0–100 =
صحة 30٪ + سرعة استيراد 15٪ + اكتمال دخول 15٪ + **استدعاء 25٪ + SLO دور 15٪**.
مكوّن الاستدعاء ميزان معلن: 100 استدعاء ناجح، 40 بناء فقط بلا عقد استدعاء
(بعض المدراء)، 0 فشل أو غير مُقاس. الطبقات S/A/B/C عتباتها معلنة في
``TIER_THRESHOLDS``. الترتيب مستقر حتمياً: الدرجة ثم الاسم.

**ميزانيات SLO لكل دور (ب1.4):** ``ROLE_SLO_BUDGETS`` يعلن ميزانية استيراد
واستدعاء لكل دور (tool/manager/service)؛ المخالفة تخفض مكوّن SLO خطياً حتى
الصفر عند 3× الميزانية، فتهبط الطبقة آلياً — والمثال الحي: ``test_runner``
بطيء زائف مقيس (3.4 ثانية) فيهبط من S.
"""

from __future__ import annotations

import time

from src.fleet.conformance import SilentBackend, ensure_src_on_path
from src.fleet.record import AgentRecord

__all__ = [
    "benchmark",
    "rank",
    "tier_of",
    "SCORE_WEIGHTS",
    "TIER_THRESHOLDS",
    "ROLE_SLO_BUDGETS",
    "SLO_OVERSHOOT_CAP",
]

#: أوزان مكونات الدرجة — مجموعها 1.0 ومعلنة لتُناقش لا لتُخمَّن (ب1.3).
SCORE_WEIGHTS = {
    "health": 0.30,
    "speed": 0.15,
    "entry": 0.15,
    "invoke": 0.25,
    "slo": 0.15,
}

#: عتبات الطبقات (>=): S ممتاز، A جيد، B مقبول، C بحاجة عمل.
TIER_THRESHOLDS = {"S": 95.0, "A": 85.0, "B": 70.0}

#: ميزانيات SLO لكل دور (ب1.4) — استيراد واستدعاء بالمللي ثانية.
#: ميزانية الأداة أضيق (عمل مركّز)، والمدير/الخدمة أرحب (تنسيق وبنية).
ROLE_SLO_BUDGETS: dict[str, dict[str, float]] = {
    "tool": {"import_ms": 5.0, "run_ms": 10.0},
    "manager": {"import_ms": 10.0, "run_ms": 20.0},
    "service": {"import_ms": 15.0, "run_ms": 30.0},
}

#: مضاعف التجاوز الذي يصفّر المكوّن: عند 3× الميزانية المكوّن = 0 (خطي قبله).
SLO_OVERSHOOT_CAP = 3.0

#: ميزان الاستدعاء المعلن (ب1.3): عقد الاستدعاء بعمقه الثلاثة.
INVOKE_FULL = 100.0  # استدعاء ناجح أعاد نتيجة
INVOKE_PARTIAL = 40.0  # بُني أوفلاين لكن بلا عقد استدعاء قابل للقياس
INVOKE_NONE = 0.0  # فشل الاستدعاء أو لم يُقاس أصلاً


def tier_of(score: float) -> str:
    """طبقة الدرجة: S ≥ 95، A ≥ 85، B ≥ 70، C ما دون."""
    for name, threshold in TIER_THRESHOLDS.items():
        if score >= threshold:
            return name
    return "C"


def _decay_component(value_ms: float, budget_ms: float) -> float:
    """100 عند الالتزام بالميزانية، خطي حتى 0 عند ``SLO_OVERSHOOT_CAP``×."""
    if value_ms <= budget_ms:
        return 100.0
    cap = budget_ms * SLO_OVERSHOOT_CAP
    if value_ms >= cap:
        return 0.0
    return round(100.0 * (cap - value_ms) / (cap - budget_ms), 2)


def _invoke_component(entry: dict) -> float:
    """ميزان عقد الاستدعاء المعلن — من حقول الحِمل لا من التخمين."""
    if entry.get("call_ok"):
        return INVOKE_FULL
    probe = str(entry.get("probe", ""))
    if probe.startswith("construct-only"):
        return INVOKE_PARTIAL
    return INVOKE_NONE


def benchmark(records: list[AgentRecord], *, deep: bool = False) -> list[dict]:
    """قياس كل وكيل وإرجاع نتائجه بلا ترتيب (الترتيب عمل ``rank``).

    ``deep=True`` يشغّل الاستدعاء المحدود: وكلاء core فوق خادم صامت،
    ووكلاء novamind عبر حِمل ``probe_agent`` — كل النتائج تحمل علم
    ``mode: "fake-clock"``. ``import_ms`` يقيس الاستيراد وحده — زمن
    الاستدعاء حقله الخاص (``run_ms``) ولا يلوث قياس الاستيراد.
    """
    ensure_src_on_path()
    results: list[dict] = []
    for rec in records:
        started = time.perf_counter()
        entry_ok = False
        run_ms: float | None = None
        run_kind: str | None = None
        call_ok: bool | None = None
        import_ok = True
        probe_info: dict | None = None
        try:
            import importlib

            module = importlib.import_module(rec.module)
        except Exception:  # noqa: BLE001 — الوكيل المكسور يُقاس بصحة 0
            import_ms = round((time.perf_counter() - started) * 1000, 2)
            results.append({
                "name": rec.name,
                "framework": rec.framework,
                "import_ms": import_ms,
                "import_ok": False,
                "entrypoint_ok": False,
                "run_ms": None,
                "run_kind": None,
            })
            continue
        # استيراد فقط — القياس قبل أي استدعاء حتى لا يلوثه زمن التشغيل
        import_ms = round((time.perf_counter() - started) * 1000, 2)
        entry = getattr(module, rec.symbol, None)
        entry_ok = entry is not None
        if deep and entry_ok and rec.framework == "core":
            try:
                agent = entry(SilentBackend())  # type: ignore[misc]
                t0 = time.perf_counter()
                agent.run("benchmark ping")
                run_ms = round((time.perf_counter() - t0) * 1000, 2)
                run_kind = "invoke"
                call_ok = True
            except Exception:  # noqa: BLE001 — عقد run: لا استثناءات
                import_ok = False
        elif deep and entry_ok and rec.framework == "novamind":
            from src.fleet.probe import probe_agent

            probe_info = probe_agent(rec)
            if probe_info["call_ok"] and probe_info["run_ms"] is not None:
                run_ms = probe_info["run_ms"]
                run_kind = "invoke"
            elif probe_info["init_ok"] and probe_info["init_ms"] is not None:
                # بلا عقد استدعاء: الزمن المقيس هو البناء المعلن
                run_ms = probe_info["init_ms"]
                run_kind = "construct"
        result = {
            "name": rec.name,
            "framework": rec.framework,
            "import_ms": import_ms,
            "import_ok": import_ok,
            "entrypoint_ok": entry_ok,
            "run_ms": run_ms,
            "run_kind": run_kind,
        }
        if call_ok is not None:
            result["call_ok"] = call_ok
        if run_kind == "invoke":
            result["mode"] = "fake-clock"
        if probe_info is not None:
            result["mode"] = probe_info["mode"]
            result["probe"] = probe_info["probe"]
            result["call_ok"] = probe_info["call_ok"]
            result["init_ms"] = probe_info["init_ms"]
            result["probe_reason"] = list(probe_info["reason"])
        results.append(result)
    return results


def rank(records: list[AgentRecord], conformance: dict, bench: list[dict]) -> list[dict]:
    """دمج الصحة والقياس في درجة 0–100 وترتيب نهائي بطبقات.

    ``conformance`` ناتج ``run_conformance`` و``bench`` ناتج ``benchmark``
    على نفس الأسطول — الوكيل المفقود من أيهما يُعامل أسوأ حالة عدلاً:
    بلا قياس لا نقاط استدعاء ولا نقاط SLO (صدق معلن لا مجاملة).

    **الهوية (إطار، اسم) لا الاسم وحده**: ثمانية أسماء مشتركة بين الإطارين
    (فجوة ف2) كانت تتصادم في فهارس الاسم البسيط فيتقاسم وكيلان قياس
    وكيلٍ آخر — الفهرسة بهوية مزدوجة تلغي الالتباس قبل توحيد الأسماء.
    """
    health = {(r["framework"], r["name"]): r["status"] for r in conformance.get("reports", [])}
    health_score = {"healthy": 100.0, "degraded": 60.0, "broken": 0.0}
    bench_by_name = {(b["framework"], b["name"]): b for b in bench}

    ranked: list[dict] = []
    for rec in records:
        status = health.get((rec.framework, rec.name), "broken")
        b = bench_by_name.get((rec.framework, rec.name))
        budget = ROLE_SLO_BUDGETS.get(rec.role, ROLE_SLO_BUDGETS["tool"])
        import_ms = b["import_ms"] if b else budget["import_ms"] * SLO_OVERSHOOT_CAP
        if b and b["import_ok"]:
            speed = _decay_component(import_ms, budget["import_ms"])
        else:
            speed = 0.0
        entry = 100.0 if (b and b["entrypoint_ok"]) else 0.0
        invoke = _invoke_component(b) if b else INVOKE_NONE
        run_ms = (b or {}).get("run_ms")
        run_kind = (b or {}).get("run_kind")
        if run_ms is not None and run_kind == "invoke":
            slo = _decay_component(run_ms, budget["run_ms"])
        else:
            slo = 0.0
        score = round(
            SCORE_WEIGHTS["health"] * health_score[status]
            + SCORE_WEIGHTS["speed"] * speed
            + SCORE_WEIGHTS["entry"] * entry
            + SCORE_WEIGHTS["invoke"] * invoke
            + SCORE_WEIGHTS["slo"] * slo,
            2,
        )
        ranked.append(
            {
                "rank": 0,
                "name": rec.name,
                "framework": rec.framework,
                "category": rec.category,
                "criticality": rec.criticality,
                "role": rec.role,
                "status": status,
                "import_ms": import_ms,
                "run_ms": run_ms,
                "invoke": invoke,
                "slo": slo,
                "score": score,
                "tier": tier_of(score),
            }
        )
    ranked.sort(key=lambda r: (-r["score"], r["name"]))
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked
