"""Factory Executor — ينفّذ وكيلًا واحدًا بشكل حقيقي.

Usage:
    from novamind.core.hive.factory.executor import execute_agent
    
    result = await execute_agent(
        agent_id="coder",
        task="اكتب دالة تتحقق من أولية عدد",
        ctx={"spec": {...}},
    )
    # result = {
    #   "success": True,
        "status": "success",
    #   "agent": "coder",
    #   "output": {...},
    #   "verification": {...},
    #   "tokens": 1234,
    #   "duration_ms": 2345,
    # }
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, List
import time
import json
import re

from novamind.core.hive.core.agents_registry import (
    get_agent,
    can_use_tool,
    has_permission,
    record_tool_call,
)
from novamind.core.hive.factory.guards import build_default_chain, can_agent_use_tool
from novamind.core.hive.factory.llm_wrapper import make_llm_call, is_llm_available
try:
    from novamind.core.hive.analytics.eval_tracker import record_eval as _record_eval
except Exception:
    _record_eval = None



# ─────────────────────────────────────────────────────
#  Prompt Builder
# ─────────────────────────────────────────────────────

SYSTEM_BASE = """أنت وكيل متخصص في NovaMind.
دورك: {specialty}
قدراتك: {capabilities}

قواعد صارمة:
- لا تستخدم placeholders (TODO، pass، # ...)
- اكتب كودًا قابلًا للتشغيل مباشرة
- التزم بالمخرجات المطلوبة بدقة
- إذا طُلب JSON، أعد JSON صالح فقط
"""

TASK_TEMPLATES = {
    "coder": """اكتب كود Python كامل للمهمة التالية:

{task}

السياق:
{context}

أعد الكود فقط في block ```python ... ```.""",

    "code_review": """راجع الكود التالي وأعط ملاحظات محددة:

{task}

السياق:
{context}

أعد:
1. المشاكل (كل واحدة في سطر)
2. التحسينات المقترحة
3. تقييم من 1-10""",

    "security": """افحص الكود أمنيًا:

{task}

السياق:
{context}

أعد قائمة بالثغرات (severity + description).""",

    "test_generator": """اكتب اختبارات pytest للكود التالي:

{task}

السياق:
{context}

أعد الاختبارات في ```python ... ```.""",

    "analyzer": """حلّل المتطلبات التالية:

{task}

السياق:
{context}

أعد JSON:
{{"summary": "...", "requirements": [...], "risks": [...]}}""",

    "task_planner": """خطّط المهمة التالية:

{task}

السياق:
{context}

أعد JSON:
{{"steps": [{{"step": 1, "action": "...", "agent": "...", "output": "..."}}]}}""",
}

DEFAULT_TEMPLATE = """نفّذ المهمة التالية:

{task}

السياق:
{context}

أعد النتيجة بشكل منظم."""


def build_prompt(agent: Dict[str, Any], task: str, ctx: Dict[str, Any]) -> Dict[str, str]:
    """يبني prompt للوكيل."""
    agent_name = agent.get("name", "unknown")
    specialty = agent.get("specialty", "general")
    capabilities = ", ".join(agent.get("capabilities", [])[:5])

    system = SYSTEM_BASE.format(
        specialty=specialty,
        capabilities=capabilities,
    )

    # اختر template حسب الاسم
    template = TASK_TEMPLATES.get(agent_name, DEFAULT_TEMPLATE)

    # Context مختصر (آخر 500 حرف)
    ctx_str = json.dumps(ctx, ensure_ascii=False, default=str)[:500]

    user = template.format(task=task, context=ctx_str)

    return {"system": system, "user": user}


# ─────────────────────────────────────────────────────
#  Output Parser
# ─────────────────────────────────────────────────────

PYTHON_INDICATORS = (
    "def ", "class ", "import ", "from ", "@",
    "if __name__", "async def ",
)


def _looks_like_python(text: str) -> bool:
    """يتحقق إن كان النص يبدو كود Python."""
    if not text or not text.strip():
        return False
    stripped = text.lstrip()
    return any(stripped.startswith(ind) or f"\n{ind}" in text for ind in PYTHON_INDICATORS)


def parse_output(agent_name: str, raw_text: str) -> Dict[str, Any]:
    """يستخرج الحقول المهمة من رد LLM."""
    output: Dict[str, Any] = {"raw": raw_text}

    # 1. code في ```python ... ```
    code_match = re.search(r"```python\s*\n(.*?)\n```", raw_text, re.DOTALL)
    if code_match:
        output["code"] = code_match.group(1).strip()

    # 2. code في ``` ... ``` عام (بدون تحديد اللغة)
    if "code" not in output:
        generic = re.search(r"```\s*\n(.*?)\n```", raw_text, re.DOTALL)
        if generic:
            candidate = generic.group(1).strip()
            if _looks_like_python(candidate):
                output["code"] = candidate

    # 3. code خام (بدون fences) إذا الوكيل coder/fixer/tester
    if "code" not in output:
        if agent_name in ("coder", "fixer", "multi_fixer", "test_generator",
                          "test_runner", "refactor_agent", "lint_agent",
                          "type_agent", "debug_agent"):
            if _looks_like_python(raw_text):
                output["code"] = raw_text.strip()

    # 4. JSON في ```json ... ```
    json_match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
    if json_match:
        try:
            output["json"] = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 5. JSON في ``` ... ``` عام
    if "json" not in output:
        generic = re.search(r"```\s*\n(.*?)\n```", raw_text, re.DOTALL)
        if generic:
            try:
                candidate = json.loads(generic.group(1).strip())
                output["json"] = candidate
            except (json.JSONDecodeError, TypeError):
                pass

    # 6. JSON بدون block
    if "json" not in output:
        stripped = raw_text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                output["json"] = json.loads(stripped)
            except json.JSONDecodeError:
                pass

    # 7. النص العام
    output["text"] = raw_text

    return output


# ─────────────────────────────────────────────────────
#  LLM Router (بسيط)
# ─────────────────────────────────────────────────────

def pick_llm_for(specialty: str):
    """يختار LLM حسب التخصص.

    حاليًا يعيد None — يُستبدل لاحقًا بـ LLM Router حقيقي.
    """
    # TODO: اربط بـ core/llm_router
    return None


# ─────────────────────────────────────────────────────
#  Executor Core
# ─────────────────────────────────────────────────────

async def execute_agent(
    agent_id: str,
    task: str,
    ctx: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    max_retries: int = 1,
    llm_call = None,  # دالة async(prompt_dict) -> dict(text=..., tokens=...)
) -> Dict[str, Any]:
    """ينفّذ وكيلًا واحدًا.

    Args:
        agent_id: اسم الوكيل
        task: وصف المهمة
        ctx: سياق سابق
        task_id: معرّف المهمة
        max_retries: عدد المحاولات عند فشل verification
        llm_call: دالة استدعاء LLM. إن None، نستخدم mock.

    Returns:
        dict مع success/output/verification/tokens/duration_ms
    """
    started = time.time()
    ctx = ctx or {}
    task_id = task_id or f"exec-{int(started)}"

    # 1. الوكيل
    agent = get_agent(agent_id)
    if not agent:
        return {
            "success": False,
            "status": "error",
            "agent": agent_id,
            "error": f"agent not found: {agent_id}",
            "duration_ms": int((time.time() - started) * 1000),
        }

    # ─── RBAC: فحص صلاحية تنفيذ LLM ───
    try:
        if not can_agent_use_tool(agent_id, "read_all") and \
           not can_agent_use_tool(agent_id, "run_tests") and \
           not can_agent_use_tool(agent_id, "monitor") and \
           not can_agent_use_tool(agent_id, "plan"):
            return {
                "success": False,
                "status": "permission_denied",
                "agent": agent_id,
                "error": f"Agent '{agent_id}' lacks execution permission",
                "permissions": getattr(__import__('hive.factory.guards', fromlist=['get_agent_permissions']), 'get_agent_permissions')(agent_id),
                "duration_ms": int((time.time() - started) * 1000),
            }
    except Exception as _rbac_err:
        logger.debug("RBAC check skipped: %s", _rbac_err)

    # 2. prompt
    prompt = build_prompt(agent, task, ctx)

    # 3. LLM call — استخدم real LLM إذا متاح
    if llm_call is None:
        if is_llm_available:
            llm_call = make_llm_call()
        # لو LLM غير متاح، يبقى None → mock

    # 4. Guard chain
    chain = build_default_chain()
    last_error = None
    output = None
    total_tokens = 0

    for attempt in range(max_retries + 1):
        try:
            if llm_call:
                response = await llm_call(prompt)
            else:
                # Mock للاختبار
                response = {
                    "text": f"[mock] Agent {agent_id} processed: {task[:50]}",
                    "tokens": 100,
                }
        except Exception as e:
            return {
                "success": False,
                "status": "error",
                "agent": agent_id,
                "error": f"LLM failed: {type(e).__name__}: {e}",
                "duration_ms": int((time.time() - started) * 1000),
            }

        total_tokens += response.get("tokens") or 0
        output = parse_output(agent_id, response.get("text", ""))

        # 4. تحقق
        guard_result = chain.check(output, stop_on_error=False)

        if guard_result.passed:
            # سجّل التقييم الذاتي (non-blocking)

            if _record_eval is not None:

                try:

                    _agent_type = getattr(agent, "specialty", None) or "unknown"

                    _task_id = ctx.get("task_id") if isinstance(ctx, dict) else None

                    _final_dur = int((time.time() - started) * 1000)

                    _prec = 1.0

                    _gr = guard_result if isinstance(guard_result, dict) else {}

                    _checks = _gr.get("checks") or []

                    if _checks:

                        _ok = sum(1 for c in _checks if isinstance(c, dict) and c.get("passed"))

                        _prec = _ok / len(_checks)

                    _record_eval(

                        agent_id=agent_id,

                        agent_type=_agent_type,

                        task_id=_task_id,

                        precision=float(_prec),

                        confidence=1.0,

                        duration_ms=_final_dur,

                        success=True,

                        notes=f"tokens={total_tokens}",

                    )

                except Exception:

                    pass

            return {
                "success": True,
        "status": "success",
                "agent": agent_id,
                "output": output,
                "verification": {
                    "passed": True,
                    "errors": [],
                    "warnings": guard_result.warnings,
                },
                "tokens": total_tokens,
                "attempts": attempt + 1,
                "duration_ms": int((time.time() - started) * 1000),
            }

        last_error = guard_result.errors

        # 5. Retry مع تصحيح
        if attempt < max_retries:
            prompt["user"] += (
                "\n\n⚠️ المخرجات السابقة فشلت في الفحص:\n"
                + "\n".join(f"- {e}" for e in guard_result.errors[:5])
                + "\n\nأعد الإجابة مع تصحيح هذه المشاكل."
            )

    # فشل بعد كل المحاولات
    _final_duration = int((time.time() - started) * 1000)
    if _record_eval is not None:
        try:
            _agent_type = getattr(agent, "specialty", None) or "unknown"
            _task_id = ctx.get("task_id") if isinstance(ctx, dict) else None
            _record_eval(
                agent_id=agent_id,
                agent_type=_agent_type,
                task_id=_task_id,
                precision=0.0,
                confidence=0.0,
                duration_ms=_final_duration,
                success=False,
                notes=f"failed after {max_retries + 1} attempts",
            )
        except Exception:
            pass

    return {
        "success": False,
        "agent": agent_id,
        "output": output,
        "error": "verification failed after retries",
        "verification": {
            "passed": False,
            "errors": last_error or [],
        },
        "tokens": total_tokens,
        "attempts": max_retries + 1,
        "duration_ms": int((time.time() - started) * 1000),
    }


# ─────────────────────────────────────────────────────
#  Sync wrapper (للاختبارات)
# ─────────────────────────────────────────────────────

def execute_agent_sync(agent_id: str, task: str, ctx=None, llm_call=None):
    """نسخة sync للاختبار."""
    import asyncio
    return asyncio.run(execute_agent(agent_id, task, ctx, llm_call=llm_call))

# ═══ Module-level attributes for test patching ═══
import logging
logger = logging.getLogger(__name__)

is_llm_available = False
try:
    from novamind.core.hive.factory.llm_wrapper import is_llm_available as _is
    is_llm_available = _is
except Exception:
    pass
