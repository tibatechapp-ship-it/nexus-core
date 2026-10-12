"""Darwinian Evolution - النخبة تُستنسخ، الفاشلون يُقصون."""
import logging
import time
from typing import Dict, List, Any, Optional, Tuple

from novamind.core.company.soldier import Soldier
from novamind.core.company.ranks import Rank
from novamind.core.company.reputation import ReputationBank

logger = logging.getLogger("Darwinian")


class DarwinianEngine:
    """محرك التطور: يطبّق الانتقاء الطبيعي على الجنود."""
    
    def __init__(
        self,
        elite_percentile: float = 0.10,   # أفضل 10% = نخبة
        weak_percentile: float = 0.15,    # أسوأ 15% = يُقصون
        clone_factor: int = 3,            # كل نخبوي يُستنسخ 3 مرات
    ):
        self.elite_pct = elite_percentile
        self.weak_pct = weak_percentile
        self.clone_factor = clone_factor
        self.generation = 0
        self.events: List[Dict] = []
    
    def _fitness(self, soldier: Soldier) -> float:
        """دالة اللياقة: تجمع كل مقاييس الأداء."""
        stats = soldier.stats
        return (
            stats.trust_score * 0.4 +
            stats.success_rate * 0.4 +
            (soldier.rank.value / 9.0) * 0.2 -
            (stats.hallucination_events * 0.1)
        )
    
    def evolve(
        self,
        soldiers: List[Soldier],
        bank: Optional[ReputationBank] = None,
    ) -> Dict[str, Any]:
        """يطبّق دورة تطور واحدة."""
        if len(soldiers) < 5:
            return {"status": "skipped", "reason": "not enough soldiers (min 5)"}
        
        self.generation += 1
        logger.info(f"Darwinian: generation {self.generation} ({len(soldiers)} soldiers)")
        
        # 1. حساب اللياقة
        ranked = sorted(soldiers, key=self._fitness, reverse=True)
        
        # 2. تقسيم الفئات
        n = len(ranked)
        elite_count = max(1, int(n * self.elite_pct))
        weak_count = max(1, int(n * self.weak_pct))
        
        elite = ranked[:elite_count]
        weak = ranked[-weak_count:]
        survivors = ranked[elite_count:-weak_count]
        
        # 3. الاستنساخ
        clones = []
        for e in elite:
            for i in range(self.clone_factor):
                clone = Soldier(
                    specialty=e.specialty,
                    rank=e.rank,
                    system_prompt=e.system_prompt,
                    mission=f"Clone of {e.id} (gen {self.generation})",
                )
                clones.append(clone)
                if bank:
                    bank.open_account(clone.id, initial=100)  # استنساخ يبدأ بثقة أعلى
        
        # 4. عقوبات الضعفاء
        if bank:
            for w in weak:
                bank.penalize(w.id, "task_failure", f"Darwinian: weak (gen {self.generation})")
        
        # 5. تسجيل الحدث
        event = {
            "generation": self.generation,
            "total_before": n,
            "elite_count": len(elite),
            "weak_count": len(weak),
            "survivors": len(survivors),
            "clones": len(clones),
            "elite_ids": [e.id for e in elite],
            "weak_ids": [w.id for w in weak],
            "time": time.time(),
        }
        self.events.append(event)
        
        return {
            "status": "evolved",
            "generation": self.generation,
            "elite_ids": [e.id for e in elite],
            "weak_ids": [w.id for w in weak],
            "survivor_ids": [s.id for s in survivors],
            "clones": clones,
            "summary": {
                "before": n,
                "after": len(survivors) + len(clones),
                "elite_promoted": len(elite),
                "weak_removed": len(weak),
                "clones_created": len(clones),
            },
        }
    
    def stats(self) -> Dict[str, Any]:
        return {
            "generation": self.generation,
            "events": len(self.events),
            "last_event": self.events[-1] if self.events else None,
        }
