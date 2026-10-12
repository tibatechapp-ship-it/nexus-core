"""
NovaMind Commander — القيادة الواحدة.
يُنسّق كل شيء عبر nova._registry:
- يقرأ الوكلاء والـ pipelines
- يُخطط (Planner بسيط rule-based)
- يُنفّذ (Pipeline)
- يحفظ (History)
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("nova.commander")


class Commander:
    """
    القيادة المركزية.
    مصدر القرار: nova._registry.
    """

    def __init__(self) -> None:
        # تحقق من صحة المصدر
        from novamind.observability import metrics, traced, metered
        from novamind.registry import validate
        errors = validate()
        if errors:
            raise RuntimeError(
                f"❌ Registry invalid ({len(errors)} errors): {errors[:3]}"
            )

        self._history: List[Dict] = []

    # ═══ Core API ═══
    def execute(self, task: str, pipeline_id: Optional[str] = None) -> Dict:
        """
        ينفّذ task عبر pipeline محدد، أو يختار تلقائياً.
        يُعيد dict يحتوي: task, pipeline, result.
        """
        if pipeline_id is None:
            pipeline_id = self.choose_pipeline(task)

        logger.info(f"🎯 Commander executing: task={task!r} pipeline={pipeline_id}")

        result = self._run_pipeline(pipeline_id, task)
        entry = {
            "task": task,
            "pipeline": pipeline_id,
            "result": result,
        }
        self._history.append(entry)
        return entry

    def choose_pipeline(self, task: str) -> str:
        """يختار pipeline بناءً على task (rule-based بسيط)."""
        from novamind.observability import metrics, traced, metered
        from novamind.registry import all_pipeline_ids
        pipelines = set(all_pipeline_ids())

        task_lower = task.lower()
        rules = [
            ("bug_fix",        ["bug", "fix", "error", "issue", "crash"]),
            ("code_review",    ["review", "check", "audit", "lint"]),
            ("deploy",         ["deploy", "release", "ship", "publish"]),
            ("system_creation",["create", "build", "generate", "make"]),
        ]
        for pid, keywords in rules:
            if pid in pipelines and any(kw in task_lower for kw in keywords):
                return pid

        # افتراضي: code_review إن وُجد، وإلا أول pipeline
        if "code_review" in pipelines:
            return "code_review"
        if pipelines:
            return sorted(pipelines)[0]
        raise RuntimeError("لا pipelines متاحة")

    def _run_pipeline(self, pipeline_id: str, task: str) -> Dict:
        """يشغّل pipeline."""
        try:
            from hive.factory.pipeline import run_pipeline_sync
        except ImportError as e:
            logger.error(f"cannot import pipeline: {e}")
            return {"ok": False, "error": f"pipeline unavailable: {e}"}

        try:
            result = run_pipeline_sync(
                pipeline_id=pipeline_id,
                task=task,
                stop_on_failure=False,
            )
            if isinstance(result, dict):
                return result
            return {"ok": True, "result": result}
        except Exception as e:
            logger.exception(f"pipeline {pipeline_id} failed")
            return {"ok": False, "error": str(e)[:200]}

    # ═══ Info ═══
    def stats(self) -> Dict:
        """إحصاءات القيادة."""
        from novamind.observability import metrics, traced, metered
        from novamind.registry import (
            stats as _registry_stats,
            all_pipeline_ids,
        )
        return {
            "registry": _registry_stats(),
            "history_count": len(self._history),
            "available_pipelines": all_pipeline_ids(),
        }

    def history(self) -> List[Dict]:
        """كل المهام المنفّذة."""
        return list(self._history)

    # ═══ Info: متاح ═══
    def available_agents(self) -> List[str]:
        """الأسماء الرسمية للوكلاء."""
        from novamind.observability import metrics, traced, metered
        from novamind.registry import all_agent_names
        return all_agent_names()

    def available_pipelines(self) -> List[str]:
        """كل pipelines."""
        from novamind.observability import metrics, traced, metered
        from novamind.registry import all_pipeline_ids
        return all_pipeline_ids()


__all__ = ["Commander"]
