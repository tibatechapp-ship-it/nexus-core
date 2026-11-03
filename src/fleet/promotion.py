"""Fleet Promotion — بوابة ترقية الطبقة عبر evalsuite (ب3.2 — v1.50.0).

يغلق باب الترقية الاجتماعية: **لا ترقية وكيل إلى طبقة S إلا بنجاح فعلي
في مهامه بمهام evalsuite** — لا تخصيص يدوي ولا مجاملة.

* ``eval_gate()`` — يشغّل عيّنة مهام evalsuite (فئة الوكيل) ويعيد
  ``eval_suite: passed/failed/unmeasured`` مع أسبابه. العدّاء الحقيقي
  يُحقن عبر ``runner`` (الافتراضي: عدّاء evalsuite أوفلاين حتمي) — فحص
  البوابة نفسه قابل للاختبار بغرفة عدّ مزيفة معلنة.
* ``promotion_gate()`` — القاعدة الصرفة: ترقية إلى S تتطلب
  ``eval_suite == "passed"``؛ الرفض معلن بسبب واضح (وإعادة الاختبار بعد
  الإصلاح ليست جلسة).
* ``read_log()/append_log()`` — سجل الترقية في
  ``reports/promotion_log.json``: كل بند يحمل ``eval_suite`` — وهو ما
  يظهر في تقرير الأسطول (ب3.2).

أوفلاين بالكامل: العدّاء الافتراضي يشغّل مهمة واحدة من فئة الوكيل فوق
موصل صامت — النتيجة صادقة حتى لو كانت «فاشل» (لا مجاملة قياس).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.evalsuite.runner import run_task
from src.evalsuite.tasks import by_category

__all__ = ["eval_gate", "promotion_gate", "read_log", "append_log", "PROMOTION_LOG"]

ROOT = Path(__file__).resolve().parents[2]
PROMOTION_LOG = ROOT / "reports" / "promotion_log.json"

#: محاولة واحدة كافية للحكم على البوابة (تُوسَّع لاحقاً بقاعدة مهام كاملة)
GATE_TASK_LIMIT = 1


async def _default_runner(framework: str, name: str, category: str) -> dict:
    """العدّاء الافتراضي: مهمة evalsuite واحدة من فئة الوكيل فوق موصل صامت.

    المهمة تُشغَّل على المحرك الحقيقي في مجلد معزول — أوفلاين حتمي،
    والفشل نتيجة صادقة تُعلن لا تُخفى.
    """
    from src.fleet.conformance import SilentBackend

    tasks = by_category(category) or by_category("create")
    task = tasks[0]
    record = await run_task(task, SilentBackend(), max_iterations=1)
    ok = bool(record.get("ok"))
    return {
        "eval_suite": "passed" if ok else "failed",
        "passed": 1 if ok else 0,
        "total": 1,
        "reason": str(record.get("reason", ""))[:160],
    }


def eval_gate(
    framework: str,
    name: str,
    *,
    category: str | None = None,
    runner: Callable[[str, str, str], dict] | None = None,
) -> dict:
    """بوابة evalsuite لوكيل واحد — ``eval_suite`` معلن لا مُخمَّن."""
    run = runner if runner is not None else _default_runner_sync
    if category is None:
        category = _category_of(framework, name)
    try:
        result = run(framework, name, category)
    except Exception as exc:  # noqa: BLE001 — فشل العدّاء نتيجة معلنة
        result = {
            "eval_suite": "failed",
            "passed": 0,
            "total": 0,
            "reason": f"runner: {type(exc).__name__}: {exc}"[:160],
        }
    return {
        "agent": name,
        "framework": framework,
        "category": category,
        "eval_suite": str(result.get("eval_suite", "failed")),
        "passed": int(result.get("passed", 0)),
        "total": int(result.get("total", 0)),
        "reason": str(result.get("reason", ""))[:160],
    }


def _default_runner_sync(framework: str, name: str, category: str) -> dict:
    """جسر متزامن فوق العدّاء غير المتزامن (واجهة البوابة متزامنة)."""
    import asyncio

    return asyncio.run(_default_runner(framework, name, category))


def _category_of(framework: str, name: str) -> str:
    """فئة الوكيل من الجرد — وfallback معلن عند غيابه."""
    try:
        from src.fleet.inventory import build_inventory

        for rec in build_inventory():
            if rec.framework == framework and rec.name == name:
                return rec.category
    except Exception:  # noqa: BLE001 — الجرد فاشل = فئة meta معلنة
        pass
    return "meta"


def promotion_gate(
    *,
    framework: str,
    name: str,
    current_tier: str,
    target_tier: str,
    eval_suite: str | None = None,
) -> dict:
    """القاعدة الصرفة للترقية — لا S بلا نجاح evalsuite فعلي.

    ``eval_suite`` أحد: ``passed`` / ``failed`` / ``unmeasured`` / ``None``
    (يُقرأ كـunmeasured). الترقية إلى S بلا ``passed`` تُرفض بسبب معلن.
    """
    suite = eval_suite or "unmeasured"
    allowed = True
    reason = "ok"
    if target_tier == "S" and suite != "passed":
        allowed = False
        reason = (
            f"refused: promotion to S requires eval_suite=passed "
            f"(got {suite!r}) — أعد الاختبار بعد الإصلاح"
        )
    if current_tier == "S" and target_tier not in ("S",):
        allowed = False
        reason = (
            "refused: S لا يهبط تحت A بلا بند إصلاح (دستور "
            "fleet-operations.md §2) — خارج نطاق بوابة الترقية"
        )
    return {
        "agent": name,
        "framework": framework,
        "current_tier": current_tier,
        "target_tier": target_tier,
        "eval_suite": suite,
        "allowed": allowed,
        "reason": reason,
    }


def read_log(path: Path | None = None) -> list[dict]:
    """اقرأ سجل الترقية — غيابه قائمة فارغة معلنة لا خطأ."""
    target = Path(path) if path is not None else PROMOTION_LOG
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return list(payload.get("log", []))
    except (OSError, ValueError, AttributeError):
        return []


def append_log(entry: dict, path: Path | None = None) -> list[dict]:
    """أضف بنداً لسجل الترقية مع طابعه الزمني — والبند يحمل eval_suite."""
    target = Path(path) if path is not None else PROMOTION_LOG
    log = read_log(path)
    stamped = dict(entry)
    stamped.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    stamped.setdefault("eval_suite", "unmeasured")
    log.append(stamped)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"log": log}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return log
