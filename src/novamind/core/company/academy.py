"""Academy - يصنع جنوداً جدد ويدرّبهم."""
import logging
from typing import Dict, Any, List, Optional

from novamind.core.company.soldier import Soldier
from novamind.core.company.ranks import Rank
from novamind.core.llm_router import LLMRouter

logger = logging.getLogger("Academy")

# اختبارات القبول — كل تخصص له اختبارات
TRAINING_TASKS = {
    "coder": [
        ("easy", "Write Python function add(a,b). Output only code."),
        ("medium", "Write Python function is_prime(n). Output only code."),
    ],
    "fixer": [
        ("easy", "Fix bug: def add(a,b) return a-b"),
        ("medium", "Fix bug: def sum(lst) return lst[-1]"),
    ],
    "tester": [
        ("easy", "Write pytest for def add(a,b): return a+b"),
    ],
    "security": [
        ("easy", "Review: query = f\"SELECT * FROM users WHERE id = {user_id}\""),
    ],
    "analyzer": [
        ("easy", "Break down: 'build a user auth system'"),
    ],
    "reviewer": [
        ("easy", "Review: def calc(x,y): return x+y*2"),
    ],
    "refactor": [
        ("easy", "Refactor: def f(l): r=[];\nfor i in l:\n if i%2==0: r.append(i)\nreturn r"),
    ],
    "optimizer": [
        ("easy", "Optimize: def find_max(lst): return sorted(lst)[-1]"),
    ],
    "arabic": [
        ("easy", "Translate to Arabic: 'Hello, world!'"),
    ],
    "doc": [
        ("easy", "Add docstring: def add(a,b): return a+b"),
    ],
}

class Academy:
    """أكاديمية: تصنع جندياً، تدرّبه، تمنحه اختبار قبول."""
    
    def __init__(self, llm_router: Optional[LLMRouter] = None):
        self.llm = llm_router or LLMRouter()
        self.log: List[Dict] = []
    
    async def train_soldier(
        self,
        specialty: str,
        system_prompt: str = "",
        missions: int = 2,
    ) -> Dict[str, Any]:
        """يصنع جندياً ويدرّبه على مهام تخصصه."""
        # 1. أنشئ الجندي
        soldier = Soldier(
            specialty=specialty,
            rank=Rank.RECRUIT,
            system_prompt=system_prompt or f"You are a {specialty}.",
        )
        
        logger.info(f"Training {soldier.id} ({specialty})")
        
        # 2. احصل على مهام التدريب
        tasks = TRAINING_TASKS.get(specialty, [
            ("easy", f"Do a basic {specialty} task.")
        ])[:missions]
        
        # 3. نفّذ التدريب
        import time
        for level, task in tasks:
            t0 = time.time()
            try:
                response = await self.llm.generate(task, system_prompt=soldier.system_prompt)
                dt = time.time() - t0
                # فحص بسيط للنجاح
                success = len(response.strip()) > 20 and "def" not in response or "return" in response
                soldier.record_task(success=success, duration=dt)
                self.log.append({
                    "soldier_id": soldier.id,
                    "task": task[:60],
                    "success": success,
                    "duration": round(dt, 2),
                })
            except Exception as e:
                soldier.record_task(success=False, duration=time.time() - t0)
                logger.error(f"Training failed: {e}")
        
        return {
            "soldier": soldier,
            "identity": soldier.get_identity(),
            "training_log": self.log,
        }
    
    async def close(self):
        await self.llm.close()
