import json
import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("MultiStepPlanner")

@dataclass
class PlanStep:
    step_id: int
    title: str
    description: str
    prompt: str
    depends_on: List[int] = field(default_factory=list)

@dataclass
class ExecutionPlan:
    goal: str
    total_steps: int
    steps: List[PlanStep] = field(default_factory=list)

PLANNER_SYSTEM_PROMPT = """Decompose complex requests into 1 to 4 actionable steps.
Output JSON only:
{
  "goal": "High level objective summary",
  "steps": [
    {
      "step_id": 1,
      "title": "Short title",
      "description": "What this step accomplishes",
      "prompt": "Detailed task instructions",
      "depends_on": []
    }
  ]
}
"""

class MultiStepPlanner:
    def __init__(self, llm_router: Any):
        self.llm_router = llm_router

    def _fallback_plan(self, user_prompt: str) -> ExecutionPlan:
        return ExecutionPlan(
            goal=user_prompt[:80],
            total_steps=1,
            steps=[
                PlanStep(
                    step_id=1,
                    title="مهمة مباشرة",
                    description="تنفيذ الطلب كاملاً في خطوة واحدة",
                    prompt=user_prompt,
                    depends_on=[]
                )
            ]
        )

    async def create_plan(self, user_prompt: str) -> ExecutionPlan:
        try:
            raw_response = await self.llm_router.generate(user_prompt, PLANNER_SYSTEM_PROMPT)
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if not json_match:
                return self._fallback_plan(user_prompt)

            data = json.loads(json_match.group(0))
            raw_steps = data.get("steps", [])
            if not raw_steps:
                return self._fallback_plan(user_prompt)

            steps = [
                PlanStep(
                    step_id=int(s.get("step_id", idx + 1)),
                    title=s.get("title", f"الخطوة {idx + 1}"),
                    description=s.get("description", ""),
                    prompt=s.get("prompt", user_prompt),
                    depends_on=s.get("depends_on", [])
                )
                for idx, s in enumerate(raw_steps)
            ]

            return ExecutionPlan(
                goal=data.get("goal", user_prompt[:80]),
                total_steps=len(steps),
                steps=steps
            )
        except Exception as e:
            logger.error(f"فشل التخطيط: {e}")
            return self._fallback_plan(user_prompt)
