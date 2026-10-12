"""Factory Pipeline — ينسّق الوكلاء عبر مراحل.

Usage:
    from novamind.factory.pipeline import run_factory
    
    result = await run_factory(
        spec={"name": "todo_api", "description": "..."},
        stages=["analyzer", "coder", "test_generator"],
        llm_call=my_llm_function,
    )
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timezone
import json
import time

from novamind.factory.executor import execute_agent


# ─────────────────────────────────────────────────────
#  Pipeline Stages (كل سلسلة تعرّف مراحلها)
# ─────────────────────────────────────────────────────

# V2_EXTENDED
PIPELINES: Dict[str, Dict[str, Any]] = {
    "system_creation": {
        "name": "System Creation",
        "description": "من spec → نظام كامل (production-ready)",
        "stages": [
            {"agent": "analyzer", "output_key": "analysis"},
            {"agent": "task_planner", "output_key": "plan"},
            {"agent": "coder", "output_key": "code"},
            {"agent": "lint_agent", "output_key": "lint"},
            {"agent": "type_agent", "output_key": "types"},
            {"agent": "test_generator", "output_key": "tests"},
            {"agent": "code_review", "output_key": "review"},
            {"agent": "security", "output_key": "security"},
            {"agent": "docker", "output_key": "docker"},
            {"agent": "docs_writer", "output_key": "docs"},
        ],
    },

    "bug_fix": {
        "name": "Bug Fix",
        "description": "إصلاح خطأ",
        "stages": [
            {"agent": "analyzer", "output_key": "analysis"},
            {"agent": "debug_agent", "output_key": "diagnosis"},
            {"agent": "fixer", "output_key": "fix"},
            {"agent": "test_runner", "output_key": "test_result"},
        ],
    },

    "code_review": {
        "name": "Code Review",
        "description": "مراجعة شاملة",
        "stages": [
            {"agent": "code_review", "output_key": "review"},
            {"agent": "security", "output_key": "security"},
            {"agent": "lint_agent", "output_key": "lint"},
            {"agent": "type_agent", "output_key": "types"},
        ],
    },

    "deploy": {
        "name": "Deploy",
        "description": "نشر نظام",
        "stages": [
            {"agent": "docker", "output_key": "docker"},
            {"agent": "deploy_agent", "output_key": "deployment"},
            {"agent": "monitor_agent", "output_key": "monitoring"},
        ],
    },
}


# ─────────────────────────────────────────────────────
#  Context Manager
# ─────────────────────────────────────────────────────

class PipelineContext:
    """يحمّل السياق عبر المراحل."""

    def __init__(self, initial: Optional[Dict[str, Any]] = None):
        self.data: Dict[str, Any] = initial or {}
        self.history: List[Dict[str, Any]] = []

    def update(self, output_key: str, value: Any):
        self.data[output_key] = value

    def record(self, stage_result: Dict[str, Any]):
        self.history.append({
            "agent": stage_result.get("agent"),
            "success": stage_result.get("success"),
            "duration_ms": stage_result.get("duration_ms"),
            "tokens": stage_result.get("tokens"),
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    def get_summary(self) -> Dict[str, Any]:
        total_tokens = sum(h.get("tokens", 0) for h in self.history)
        total_ms = sum(h.get("duration_ms", 0) for h in self.history)
        passed = sum(1 for h in self.history if h.get("success"))
        return {
            "stages_total": len(self.history),
            "stages_passed": passed,
            "stages_failed": len(self.history) - passed,
            "total_tokens": total_tokens,
            "total_duration_ms": total_ms,
        }


# ─────────────────────────────────────────────────────
#  Pipeline Runner
# ─────────────────────────────────────────────────────

async def run_pipeline(
    pipeline_id: str,
    task: str,
    initial_ctx: Optional[Dict[str, Any]] = None,
    llm_call: Optional[Callable] = None,
    stop_on_failure: bool = False,
    max_retries: int = 1,
) -> Dict[str, Any]:
    """يشغّل pipeline كامل.

    Args:
        pipeline_id: اسم pipeline (system_creation, bug_fix, ...)
        task: وصف المهمة
        initial_ctx: سياق ابتدائي
        llm_call: دالة استدعاء LLM
        stop_on_failure: إذا True، يتوقف عند أول فشل
        max_retries: عدد المحاولات لكل وكيل

    Returns:
        dict مع status/ctx/history/summary
    """
    started = time.time()
    pipeline = PIPELINES.get(pipeline_id)
    if not pipeline:
        return {
            "status": "invalid_pipeline",
            "error": f"unknown pipeline: {pipeline_id}",
            "available": list(PIPELINES.keys()),
        }

    ctx = PipelineContext(initial_ctx or {})
    ctx.data["__task__"] = task

    results = []
    failed = 0

    for stage in pipeline["stages"]:
        agent_id = stage["agent"]
        output_key = stage.get("output_key", agent_id)

        # نفّذ
        result = await execute_agent(
            agent_id=agent_id,
            task=task,
            ctx=ctx.data,
            llm_call=llm_call,
            max_retries=max_retries,
        )

        ctx.record(result)
        results.append(result)

        if result.get("success"):
            # احفظ الناتج
            output = result.get("output", {})
            ctx.update(output_key, output)
        else:
            failed += 1
            if stop_on_failure:
                break

    # النتيجة النهائية
    duration_ms = int((time.time() - started) * 1000)
    summary = ctx.get_summary()
    status = "done" if failed == 0 else ("partial" if failed < len(results) else "failed")

    return {
        "status": status,
        "pipeline": pipeline_id,
        "task": task,
        "results": results,
        "ctx": ctx.data,
        "history": ctx.history,
        "summary": summary,
        "duration_ms": duration_ms,
        "failed_stages": failed,
        "total_stages": len(results),
    }


# ─────────────────────────────────────────────────────
#  Sync wrapper
# ─────────────────────────────────────────────────────

def run_pipeline_sync(pipeline_id: str, task: str, **kwargs) -> Dict[str, Any]:
    import asyncio
    return asyncio.run(run_pipeline(pipeline_id, task, **kwargs))


def list_pipelines() -> List[Dict[str, str]]:
    """يرجع pipelines المتاحة."""
    return [
        {"id": pid, "name": p["name"], "description": p["description"]}
        for pid, p in PIPELINES.items()
    ]


def format_result(result: Dict[str, Any]) -> str:
    """تنسيق لـ Telegram."""
    status = result.get("status", "unknown")
    emoji = {"done": "✅", "partial": "⚠️", "failed": "❌"}.get(status, "❓")

    lines = [
        f"{emoji} *Pipeline: {result.get('pipeline', '?')}*",
        f"الحالة: {status}",
        f"المراحل: {result.get('total_stages', 0)}",
        f"فشل: {result.get('failed_stages', 0)}",
        f"المدة: {result.get('duration_ms', 0)}ms",
        "",
    ]

    summary = result.get("summary", {})
    if summary:
        lines.append(f"📊 Tokens: {summary.get('total_tokens', 0)}")
        lines.append(f"✅ نجح: {summary.get('stages_passed', 0)}")
        lines.append(f"❌ فشل: {summary.get('stages_failed', 0)}")
        lines.append("")

    history = result.get("history", [])
    if history:
        lines.append("*التفاصيل:*")
        for h in history:
            mark = "✅" if h.get("success") else "❌"
            lines.append(f"  {mark} {h.get('agent', '?')} ({h.get('duration_ms', 0)}ms)")

    return "\n".join(lines)
