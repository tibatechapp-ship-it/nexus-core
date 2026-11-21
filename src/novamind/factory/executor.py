"""Factory Executor — ينفّذ وكيلًا واحدًا بشكل حقيقي.

Usage:
    from novamind.factory.executor import execute_agent

    result = await execute_agent(
        agent_id="coder",
        task="اكتب دالة تتحقق من أولية عدد",
        ctx={"spec": {...}},
    )
    # result = {
    #   "success": True,
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
from novamind.factory.guards import (
    build_default_chain,
    can_agent_use_tool,
    get_agent_permissions,
)
from novamind.factory.llm_wrapper import make_llm_call, is_llm_available

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
    "def ",
    "class ",
    "import ",
    "from ",
    "@",
    "if __name__",
    "async def ",
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
        if agent_name in (
            "coder",
            "fixer",
            "multi_fixer",
            "test_generator",
            "test_runner",
            "refactor_agent",
            "lint_agent",
            "type_agent",
            "debug_agent",
        ):
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
    """يختار LLM حسب التخصص عبر موجّه الإطار المركزي.

    الربط المعماري ب2.3 (v1.49.1): الوكيل يُختار من ``core/llm_router``
    (المفرد الوحيد للتوجيه) — وأي فشل استيراد/بناء يعيد ``None`` معلنًا
    لا استثناء، فيبقى المسار المحلي بديلًا آمنًا.
    """
    try:
        from novamind.core.llm_router import get_router

        # Return the central router even when unconfigured so callers can
        # inspect capability and receive its explicit no-provider failure.
        # An empty provider list is not a synthetic execution capability.
        return get_router()
    except Exception:
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
    llm_call=None,  # دالة async(prompt_dict) -> dict(text=..., tokens=...)
) -> Dict[str, Any]:
    """ينفّذ وكيلًا واحدًا.

    Args:
        agent_id: اسم الوكيل
        task: وصف المهمة
        ctx: سياق سابق
        task_id: معرّف المهمة
        max_retries: عدد المحاولات عند فشل verification
        llm_call: مزود LLM حقيقي أو callable اختباري محقون صراحةً.

    Returns:
        dict مع success/output/verification/tokens/duration_ms
    """
    started = time.time()
    if not isinstance(agent_id, str) or not agent_id.strip():
        return {
            "success": False, "status": "invalid_request",
            "agent": str(agent_id), "error": "agent_id must be non-empty",
            "duration_ms": 0,
        }
    if not isinstance(task, str) or not task.strip():
        return {
            "success": False, "status": "invalid_request",
            "agent": agent_id, "error": "task must be non-empty",
            "duration_ms": 0,
        }
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        return {
            "success": False, "status": "invalid_request",
            "agent": agent_id, "error": "max_retries must be a non-negative integer",
            "duration_ms": 0,
        }
    ctx = ctx or {}
    task_id = task_id or f"exec-{int(started)}"

    # 1. Resolve only registered agents; registry failures never create mocks.
    try:
        agent = get_agent(agent_id)
    except KeyError:
        return {
            "success": False,
            "status": "agent_not_registered",
            "agent": agent_id,
            "error": f"agent not found: {agent_id}",
            "duration_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "registry_unavailable",
            "agent": agent_id,
            "error": f"canonical registry lookup failed: {type(exc).__name__}",
            "duration_ms": int((time.time() - started) * 1000),
        }

    # RBAC: both execution entrypoints use the same canonical policy.
    try:
        authorized = any(
            can_agent_use_tool(agent_id, permission)
            for permission in ("read_all", "run_tests", "monitor", "plan")
        )
        permissions = get_agent_permissions(agent_id)
    except Exception as exc:
        return {
            "success": False,
            "status": "authorization_unavailable",
            "agent": agent_id,
            "error": f"RBAC check failed closed: {type(exc).__name__}",
            "duration_ms": int((time.time() - started) * 1000),
        }
    if not authorized:
        return {
            "success": False,
            "status": "permission_denied",
            "agent": agent_id,
            "error": f"Agent '{agent_id}' lacks execution permission",
            "permissions": permissions,
            "duration_ms": int((time.time() - started) * 1000),
        }

    # 2. prompt
    prompt = build_prompt(agent, task, ctx)

    # 3. A real provider is mandatory unless a callable is explicitly injected.
    if llm_call is None:
        if is_llm_available():
            llm_call = make_llm_call(max_retries=0)
        else:
            return {
                "success": False,
                "status": "llm_unavailable",
                "agent": agent_id,
                "error": "No real LLM provider is configured; no simulated output was generated.",
                "duration_ms": int((time.time() - started) * 1000),
            }

    if not callable(llm_call):
        return {
            "success": False,
            "status": "llm_unavailable",
            "agent": agent_id,
            "error": "No callable real LLM provider is available.",
            "duration_ms": int((time.time() - started) * 1000),
        }

    # 4. Guard chain
    chain = build_default_chain()
    last_error = None
    output = None
    total_tokens = 0

    for attempt in range(max_retries + 1):
        try:
            response = await llm_call(prompt)
        except Exception as e:
            last_error = f"LLM failed: {type(e).__name__}: {e}"
            if attempt < max_retries:
                continue
            return {
                "success": False,
                "status": "llm_provider_error",
                "agent": agent_id,
                "error": last_error[:300],
                "attempts": attempt + 1,
                "duration_ms": int((time.time() - started) * 1000),
            }

        if not isinstance(response, dict):
            return {
                "success": False,
                "status": "invalid_llm_response",
                "agent": agent_id,
                "error": "LLM callable must return a response dictionary",
                "duration_ms": int((time.time() - started) * 1000),
            }
        if response.get("ok") is False:
            last_error = str(response.get("error") or "LLM provider request failed")
            if attempt < max_retries:
                continue
            return {
                "success": False,
                "status": "llm_provider_error",
                "agent": agent_id,
                "error": last_error[:300],
                "provider": response.get("provider", "unknown"),
                "attempts": attempt + 1,
                "duration_ms": int((time.time() - started) * 1000),
            }

        if response.get("simulated") is True:
            return {
                "success": False,
                "status": "simulated_provider_rejected",
                "agent": agent_id,
                "error": "Simulated LLM output cannot be accepted as a real agent execution.",
                "duration_ms": int((time.time() - started) * 1000),
            }

        provider_name = response.get("provider")
        model_name = response.get("model")
        if (
            response.get("ok") is not True
            or response.get("simulated") is not False
            or not isinstance(provider_name, str)
            or not provider_name.strip()
            or provider_name.strip().lower() in {
                "mock", "mock-provider", "offline", "none", "unknown", "router", "auto"
            }
            or not isinstance(model_name, str)
            or not model_name.strip()
        ):
            return {
                "success": False,
                "status": "unverified_provider_response",
                "agent": agent_id,
                "error": (
                    "Provider response lacks explicit real-execution evidence "
                    "(ok=true, simulated=false, provider and model identifiers)."
                ),
                "provider": str(provider_name or "unknown")[:100],
                "duration_ms": int((time.time() - started) * 1000),
            }

        response_text = response.get("text", "")
        if not isinstance(response_text, str) or not response_text.strip():
            last_error = "LLM provider returned an empty response."
            if attempt < max_retries:
                continue
            return {
                "success": False,
                "status": "empty_llm_response",
                "agent": agent_id,
                "error": last_error,
                "provider": response.get("provider", "unknown"),
                "attempts": attempt + 1,
                "duration_ms": int((time.time() - started) * 1000),
            }

        total_tokens += int(response.get("tokens", 0) or 0)
        output = parse_output(agent_id, response_text)

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
    """نسخة sync مع فحص أمني (Gatekeeper Layer 1).

    Security:
    - يفحص المهمة عبر Gatekeeper قبل التنفيذ
    - يمكن تعطيله بـ NOVAMIND_SECURITY=off
    - يرفع SecurityError عند الحظر
    """
    import asyncio
    import os

    if os.environ.get("NOVAMIND_SECURITY", "on").lower() != "off":
        try:
            from novamind.core.security_gatekeeper import gatekeeper

            verdict = gatekeeper.analyze(task)
            if verdict.is_blocked:
                raise SecurityError(
                    f"Blocked by Gatekeeper: {verdict.reason}",
                    verdict=verdict,
                )
        except ImportError:
            pass

    return asyncio.run(execute_agent(agent_id, task, ctx, llm_call=llm_call))


class SecurityError(RuntimeError):
    """Raised when security gatekeeper blocks a request."""

    def __init__(self, message: str, verdict=None):
        super().__init__(message)
        self.verdict = verdict
