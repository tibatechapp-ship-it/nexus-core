"""Agent Router — routes user messages through fallback chain:
1. Agents (via MoE Router)
2. LLM Router (Ollama -> GLM -> Groq pool)
3. Fallback
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("AgentRouter")


async def route_message(text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Route a user message through the fallback chain."""
    context = context or {}
    t0 = time.time()

    # Layer 1: Agents via MoE Router
    try:
        result = await _try_agents(text, context)
        if result.get("success"):
            return {
                "source": "agent",
                "text": result["text"],
                "meta": {
                    "agent": result.get("agent"),
                    "sub_agents": result.get("sub_agents", []),
                    "reasoning": result.get("reasoning", ""),
                    "duration_ms": int((time.time() - t0) * 1000),
                },
            }
    except Exception as e:
        logger.warning(f"Agent layer failed: {e}")

    # Layer 2: LLM Router (Ollama -> GLM -> Groq)
    try:
        result = await _try_llm_router(text)
        if result.get("success"):
            return {
                "source": "llm",
                "text": result["text"],
                "meta": {
                    "provider": result.get("provider", "unknown"),
                    "duration_ms": int((time.time() - t0) * 1000),
                },
            }
    except Exception as e:
        logger.warning(f"LLM router layer failed: {e}")

    # Layer 3: Fallback
    return {
        "source": "fallback",
        "text": (
            "لم أتمكن من معالجة طلبك حاليًا. جرّب:\n\n"
            "• /hive_status - حالة HiveLoop\n"
            "• /nm_status - حالة NovaMind\n"
            "• /hive_list - قائمة الوكلاء\n"
            "• /start - كل الأوامر"
        ),
        "meta": {"duration_ms": int((time.time() - t0) * 1000)},
    }


async def _try_agents(text: str, context: Dict) -> Dict[str, Any]:
    """Try to route to specialized agents."""
    try:
        from novamind.core.llm_router import LLMRouter
        from novamind.core.moe_router import SemanticMoERouter
        from hive.runtime.adapter import AdapterRegistry
    except Exception as e:
        return {"success": False, "error": f"import failed: {e}"}

    try:
        llm = LLMRouter()
        moe = SemanticMoERouter(llm)
        decision = await moe.route_task(text)

        if not decision or not decision.primary_agent:
            return {"success": False, "error": "no agent selected"}

        reg = AdapterRegistry()
        agent = reg.get(decision.primary_agent)
        if not agent:
            return {"success": False, "error": f"agent {decision.primary_agent} not found"}

        import inspect as _inspect

        response = None
        for method_name in ("run", "call_llm"):
            if not hasattr(agent, method_name):
                continue
            try:
                response = getattr(agent, method_name)(text)
                # انتظر أي كائن awaitable (coroutine, Future, ...)
                if _inspect.isawaitable(response):
                    response = await response
                # في حال أُعيد coroutine مغلّف
                if _inspect.isawaitable(response):
                    response = await response
                if response is not None and response != "":
                    break
            except Exception as e:
                logger.warning(f"agent.{method_name} failed: {e}")
                response = None

        # رفض كائنات coroutine غير محسومة
        if _inspect.isawaitable(response):
            logger.warning(f"agent returned unresolved awaitable: {response!r}")
            response = None

        if response:
            if isinstance(response, dict):
                text_out = (
                    response.get("text")
                    or response.get("response")
                    or response.get("output")
                    or str(response)
                )
            elif hasattr(response, "text"):
                text_out = str(response.text)
            else:
                text_out = str(response)

            # ارفض الكائنات التي تبدو coroutine
            if "coroutine object" in text_out:
                logger.warning(f"agent returned coroutine repr: {text_out[:80]}")
                return {"success": False, "error": "agent coroutine not awaited"}

            return {
                "success": True,
                "text": text_out,
                "agent": decision.primary_agent,
                "sub_agents": decision.sub_agents,
                "reasoning": decision.reasoning,
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": False, "error": "agent produced no response"}


async def _try_llm_router(text: str) -> Dict[str, Any]:
    """Try the central LLM router."""
    try:
        from novamind.core.llm_router import LLMRouter
    except Exception as e:
        return {"success": False, "error": f"import failed: {e}"}

    try:
        router = LLMRouter()
        response = await router.generate(text)
        if response:
            provider = getattr(router, "last_provider", None) or "llm-router"
            return {
                "success": True,
                "text": str(response),
                "provider": str(provider),
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": False, "error": "router returned empty"}
