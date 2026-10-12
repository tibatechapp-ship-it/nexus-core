"""Smart Router with Few-shot Learning"""
from typing import Dict, Any
from novamind.core.enhanced_router import get_enhanced_router
from novamind.core.few_shot_learner import get_few_shot_learner

class SmartRouter:
    def __init__(self):
        self.router = get_enhanced_router()
        self.learner = get_few_shot_learner()

    def generate(self, prompt, task_description=None, **kwargs):
        if task_description:
            enhanced_prompt = self.learner.enhance_prompt(prompt, task_description)
        else:
            enhanced_prompt = prompt
        result = self.router.generate(prompt=enhanced_prompt, **kwargs)
        if result.get('ok') and task_description:
            code = result.get('text', '')
            if code and len(code) > 50:
                self.learner.record_solution(
                    task_description=task_description,
                    code=code,
                    success=True,
                    metadata={'provider': result.get('provider'), 'latency_ms': result.get('latency_ms')}
                )
        return result

    def get_report(self):
        r = self.router.get_full_report()
        s = self.learner.get_stats()
        return r + "\n\nFEW-SHOT STATS: " + str(s)

_sr = None
def get_smart_router():
    global _sr
    if _sr is None:
        _sr = SmartRouter()
    return _sr
