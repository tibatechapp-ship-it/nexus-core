import json
import re
import logging
from typing import List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("MoERouter")

@dataclass
class RoutingDecision:
    primary_agent: str
    sub_agents: List[str] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 1.0

AGENT_TAXONOMY = {
    "analyzer": "High-level code analysis and requirement breakdown",
    "arabic": "Arabic language processing, RTL, translation, localized context",
    "coder": "General software engineering and feature implementation",
    "fixer": "Targeted bug fixing and security patching",
    "test_generator": "Generating unit and integration tests",
    "tester": "QA strategy and edge case verification",
    "sec_vulnerability": "Security review, SQLi, XSS, and input sanitization",
    "optimizer": "Performance profiling and query optimization"
}

ROUTER_SYSTEM_PROMPT = """You are the MoE Semantic Router for NovaMind Agent Engine.
Analyze the user request and route it to the best primary agent and optional sub-agents from this taxonomy:
{taxonomy}

Return strict JSON only:
{{
  "primary_agent": "agent_name",
  "sub_agents": ["sub_agent1"],
  "reasoning": "Short explanation in Arabic"
}}
"""

class SemanticMoERouter:
    def __init__(self, llm_router: Any):
        self.llm_router = llm_router

    def _fallback_route(self, prompt: str) -> RoutingDecision:
        p_lower = prompt.lower()
        if "اختبار" in p_lower or "test" in p_lower:
            return RoutingDecision(primary_agent="test_generator", sub_agents=["tester"], reasoning="توجيه أوتوماتيكي لوكلاء الاختبار")
        if "ثغرة" in p_lower or "sql" in p_lower or "xss" in p_lower or "أمان" in p_lower:
            return RoutingDecision(primary_agent="sec_vulnerability", sub_agents=["fixer"], reasoning="توجيه أوتوماتيكي لوكلاء الأمن البرمجي")
        return RoutingDecision(primary_agent="coder", sub_agents=["arabic"], reasoning="توجيه أوتوماتيكي لوكيل التطوير العام")

    async def route_task(self, user_prompt: str) -> RoutingDecision:
        taxonomy_str = "\n".join([f"- {k}: {v}" for k, v in AGENT_TAXONOMY.items()])
        sys_prompt = ROUTER_SYSTEM_PROMPT.format(taxonomy=taxonomy_str)

        try:
            raw_res = await self.llm_router.generate(user_prompt, sys_prompt)
            json_match = re.search(r'\{.*\}', raw_res, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                p_agent = data.get("primary_agent", "coder")
                s_agents = [s for s in data.get("sub_agents", []) if s in AGENT_TAXONOMY and s != p_agent]
                return RoutingDecision(
                    primary_agent=p_agent if p_agent in AGENT_TAXONOMY else "coder",
                    sub_agents=s_agents,
                    reasoning=data.get("reasoning", "توجيه دلالي مستند للنموذج")
                )
        except Exception as e:
            logger.error(f"خطأ أثناء التوجيه الدلالي: {e}")

        return self._fallback_route(user_prompt)
