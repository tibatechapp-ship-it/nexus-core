import asyncio
import logging
from typing import Dict, Any, List
from novamind.core.llm_router import LLMRouter
from novamind.core.moe_router import SemanticMoERouter
from novamind.agents.factory import AgentFactory

logger = logging.getLogger("Orchestrator")

class Orchestrator:
    """منسق النظام المطور بدعم التوجيه الدلالي MoE وتنفيذ الوكلاء المتوازي"""

    def __init__(self):
        self.llm_router = LLMRouter()
        self.moe_router = SemanticMoERouter(llm_router=self.llm_router)
        self.agent_factory = AgentFactory()

    async def _run_agent_safe(self, agent_name: str, prompt: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """تشغيل وكيل مفرد مع معالجة الأخطاء والقيود"""
        try:
            agent = self.agent_factory.get(agent_name)
            output = await agent.run(prompt, context=context, llm=self.llm_router)
            return {"agent": agent_name, "status": "success", "output": output}
        except Exception as e:
            logger.error(f"خطأ تشغيل الوكيل {agent_name}: {e}")
            return {"agent": agent_name, "status": "error", "error": str(e)}

    async def run_pipeline(self, user_prompt: str) -> Dict[str, Any]:
        logger.info("=== بدء تنفيذ Proactive Pipeline (v12.0) ===")
        
        # 1. التوجيه عبر MoE Router
        routing_decision = await self.moe_router.route_task(user_prompt)

        # 2. تنفيذ الوكيل الرئيسي
        primary_res = await self._run_agent_safe(routing_decision.primary_agent, user_prompt)

        # 3. تنفيذ الوكلاء المساعدين بالتوازي
        sub_results = []
        if routing_decision.sub_agents:
            tasks = [self._run_agent_safe(sub, user_prompt) for sub in routing_decision.sub_agents]
            sub_results = await asyncio.gather(*tasks)

        return {
            "status": "completed",
            "routing_info": {
                "primary_agent": routing_decision.primary_agent,
                "sub_agents": routing_decision.sub_agents,
                "reasoning": routing_decision.reasoning
            },
            "primary_output": primary_res,
            "sub_outputs": sub_results
        }
