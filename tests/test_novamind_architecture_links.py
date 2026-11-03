"""اختبارات الربطين المعماريين (ب2.2/ب2.3 — v1.49.1).

فجوتا ف3 سابقتا الربط بمسارين محليين يعملان دون جهاز التوجيه المركزي:

* **ب2.2**: ``NovaMindOrchestrator`` يقرأ طول الطابور من
  ``novamind.core.queue_manager.TaskQueue`` فعليًا (قراءة متزامنة آمنة)
  — والغياب صفر معلن لا تخمين.
* **ب2.3**: ``pick_llm_for(specialty)`` في المنفذين (factory و
  hive/factory) يعيد موجّه الإطار المركزي ``core/llm_router.get_router()``
  — والفشل ``None`` معلن لا استثناء. كل ذلك أوفلاين فوق مزوّد زائف.
"""

from __future__ import annotations

import asyncio

from novamind.core.automation.orchestrator import NovaMindOrchestrator
from novamind.core.queue_manager import Task, TaskQueue


def _build_orchestrator(tmp_path, queue):
    return NovaMindOrchestrator(
        factory=None,
        trainer_pool=None,
        quality_gate=None,
        bridge=None,
        commander=None,
        base_dir=tmp_path,
        queue=queue,
    )


def test_orchestrator_reads_queue_manager(tmp_path) -> None:
    """ب2.2: طول الطابور من Queue Manager فعليًا لا صفر معلن زورًا."""
    queue = TaskQueue()
    asyncio.run(queue.push(Task(priority=1, id="t1", kind="review")))
    orch = _build_orchestrator(tmp_path, queue)
    metrics = orch._collect_metrics()
    assert metrics["queue_length"] == queue.size() == 1


def test_orchestrator_without_queue_declares_zero(tmp_path) -> None:
    """ب2.2: غياب الطابور = صفر معلن، لا انفجار ولا تخمين."""
    orch = _build_orchestrator(tmp_path, None)
    assert orch._collect_metrics()["queue_length"] == 0


def _pick_llm_callables():
    from novamind.core.hive.factory.executor import pick_llm_for as hive_pick
    from novamind.factory.executor import pick_llm_for as factory_pick

    return factory_pick, hive_pick


def test_pick_llm_for_links_both_executors_to_central_router() -> None:
    """ب2.3: النسختان تعيدان موجّه الإطار المركزي — لا مسار محلي معزول."""
    factory_pick, hive_pick = _pick_llm_callables()
    for pick in (factory_pick, hive_pick):
        router = pick("code")
        assert router is not None, "الربط ب2.3 انقطع — pick_llm_for أعاد None"
        # عقد الموجّه المركزي: واجهة التوجيه حاضرة والمزوّدون معلنون
        assert hasattr(router, "generate_for_task")
        assert hasattr(router, "generate")
        assert getattr(router, "providers", None), "موجّه بلا مزودين"


def test_pick_llm_for_is_importable_via_factory_package() -> None:
    """الواجهة العامة للـfactory لا تفقد pick_llm_for (عقد التوافق)."""
    import novamind.factory as factory_pkg

    assert hasattr(factory_pkg, "pick_llm_for")
