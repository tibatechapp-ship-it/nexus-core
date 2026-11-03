"""Fleet Conformance — فحص مطابقة لكل وكيل في الأسطول.

لكل سجل يجيب الفحص ثلاثة أسئلة بترتيب صرامة تصاعدي:

1. **metadata** — هل بيانات الوصف مكتملة (وحدة + رمز + وصف)؟
2. **import** — هل الوحدة تُستورد فعلاً بلا شبكة وبلا LLM حقيقي؟
3. **entrypoint** — هل رمز الدخول موجود في الوحدة؟

والنتيجة حالة واحدة معلنة: ``healthy`` (كل شيء سليم) أو ``degraded``
(استورد لكن بثغرة بيانات وصف) أو ``broken`` (تعذر الاستيراد أو الدخول).

قواعد الأمان: وكلاء novamind وlegacy **لا يُنَسَّخون** (تهيئتهم غير معلنة
وقد يلمس شبكة/أقراص) — يُفحص استيرادهم وحضور الرمز فقط. الوكلاء الأساسيون
وحدهم يُبنون فعلياً فوق خادم زائف صامت، لأن عقد الإطار يضمن أن ``run``
لا يرفع استثناءات أبداً.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any

from src.fleet.record import AgentRecord

__all__ = ["run_conformance", "check_agent"]

ROOT = Path(__file__).resolve().parents[2]


class SilentBackend:
    """خادم LLM زائف: يعيد نصاً ثابتاً، بلا شبكة وبلا ساعة انتظار."""

    def generate(self, messages: Any, model: str | None = None) -> str:
        return "ok"


def ensure_src_on_path() -> None:
    """وحدات novamind تُستورد باسم ``novamind.*`` الأعلى — ضمّد ``src/``.

    هذا النمط نفسه الذي تستخدمه ``src/novamind/agents/factory.py``، فيُعامل
    كعقد بيئة معلن لا كحيلة اختبار.
    """
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.append(src)


def check_agent(record: AgentRecord, *, instantiate_core: bool = True) -> dict:
    """فحص وكيل واحد وإرجاع تقريره: status + أسباب + زمن الاستيراد."""
    reasons: list[str] = []
    import_ms = 0.0
    if not record.module or not record.symbol:
        reasons.append("metadata: module/symbol missing")
        return {"name": record.name, "framework": record.framework,
                "status": "broken", "reasons": reasons, "import_ms": import_ms}
    if not record.description:
        reasons.append("metadata: empty description")

    ensure_src_on_path()
    started = time.perf_counter()
    try:
        module = importlib.import_module(record.module)
    except Exception as exc:  # noqa: BLE001 — الفشل يُرصد لا يُنشر
        import_ms = round((time.perf_counter() - started) * 1000, 2)
        reasons.append(f"import: {type(exc).__name__}: {exc}"[:160])
        return {"name": record.name, "framework": record.framework,
                "status": "broken", "reasons": reasons, "import_ms": import_ms}
    import_ms = round((time.perf_counter() - started) * 1000, 2)

    entry = getattr(module, record.symbol, None)
    if entry is None:
        reasons.append(f"entrypoint: {record.symbol!r} not found in {record.module}")
        return {"name": record.name, "framework": record.framework,
                "status": "broken", "reasons": reasons, "import_ms": import_ms}

    if record.framework == "core" and instantiate_core:
        try:
            agent = entry(SilentBackend())  # type: ignore[call-arg]
            run = agent.run("ping")
            if not getattr(run, "ok", False):
                reasons.append("run: scripted ping returned ok=False")
        except Exception as exc:  # noqa: BLE001 — عقد run: لا استثناءات
            reasons.append(f"instantiate/run: {type(exc).__name__}: {exc}"[:160])

    status = "degraded" if reasons else "healthy"
    return {"name": record.name, "framework": record.framework,
            "status": status, "reasons": reasons, "import_ms": import_ms}


def run_conformance(records: list[AgentRecord], *, deep: bool = False) -> dict:
    """فحص الأسطول كاملاً — تقرير مجمع + تقرير لكل وكيل.

    ``deep=False`` (الافتراضي للاختبارات السريعة) يكفي بفحص الاستيراد؛
    ``deep=True`` يشغّل النسخ الفعلي للوكلاء الأساسيين (لأدوات CLI والتقارير).
    """
    reports = [check_agent(rec, instantiate_core=deep) for rec in records]
    counts = {"healthy": 0, "degraded": 0, "broken": 0}
    for rep in reports:
        counts[rep["status"]] += 1
    return {
        "checked": len(reports),
        "counts": counts,
        "reports": reports,
    }
