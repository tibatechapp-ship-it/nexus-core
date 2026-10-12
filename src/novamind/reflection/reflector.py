"""Reflector — يحسّن الردود الفاشلة."""
import asyncio
import logging
from typing import Dict, Any, Optional, Callable

from .critic import get_critic

log = logging.getLogger("Reflector")


class Reflector:
    """يحسّن الردود عبر:
    1. تقييم
    2. اقتراح تحسين
    3. إعادة المحاولة
    """

    MAX_ITERATIONS = 3

    def __init__(self, agent_call: Optional[Callable] = None):
        self.critic = get_critic()
        self.agent_call = agent_call

    def build_improvement_prompt(self, original_q: str, bad_reply: str,
                                   critique: Dict) -> str:
        """يبني prompt محسّن."""
        issues = critique.get("issues", [])
        score = critique.get("score", 0)

        prompt = f"""السؤال الأصلي: {original_q}

الرد السابق (score={score}):
{bad_reply[:500]}

مشاكل مكتشفة: {', '.join(issues)}

قدم رداً محسّناً يحل هذه المشاكل:
- كن أكثر دقة
- لا تقل "لا أعرف" إن كانت المعلومة متاحة
- أجب بإيجاز مناسب

الرد المحسّن:"""
        return prompt

    async def improve(self, question: str, initial_reply: str,
                       agent_chat_func: Callable) -> Dict[str, Any]:
        """يحاول تحسين الرد."""
        current_reply = initial_reply
        history = []

        for i in range(self.MAX_ITERATIONS):
            critique = self.critic.evaluate(question, current_reply)

            history.append({
                "iteration": i,
                "score": critique["score"],
                "needs_improvement": critique["needs_improvement"],
                "issues": critique["issues"],
            })

            if not critique["needs_improvement"]:
                log.info(f"✅ Accepted at iteration {i} (score={critique['score']})")
                return {
                    "ok": True,
                    "final_reply": current_reply,
                    "iterations": i + 1,
                    "final_score": critique["score"],
                    "history": history,
                }

            # بناء prompt محسّن
            improvement_prompt = self.build_improvement_prompt(
                question, current_reply, critique
            )

            log.info(f"🔄 Iteration {i+1}: score={critique['score']}, retrying...")

            # إعادة المحاولة
            try:
                result = await agent_chat_func(improvement_prompt)
                if result.get("ok"):
                    current_reply = result.get("reply", current_reply)
                else:
                    log.warning(f"Improvement failed: {result.get('error')}")
                    break
            except Exception as e:
                log.exception(f"Improvement exception: {e}")
                break

        # لم نصل للعتبة
        final_critique = self.critic.evaluate(question, current_reply)
        return {
            "ok": True,
            "final_reply": current_reply,
            "iterations": self.MAX_ITERATIONS,
            "final_score": final_critique["score"],
            "history": history,
            "hit_max_iterations": True,
        }


_reflector: Optional[Reflector] = None

def get_reflector() -> Reflector:
    global _reflector
    if _reflector is None:
        _reflector = Reflector()
    return _reflector
