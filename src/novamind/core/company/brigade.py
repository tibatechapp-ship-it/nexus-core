"""Brigade - كتيبة متخصصة من الجنود."""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from novamind.core.company.soldier import Soldier
from novamind.core.company.ranks import Rank

logger = logging.getLogger("Brigade")

class Brigade:
    """كتيبة: مجموعة جنود من نفس التخصص."""
    
    def __init__(self, name: str, specialty: str):
        self.name = name
        self.specialty = specialty
        self.soldiers: List[Soldier] = []
        self.created_at = datetime.now()
        self.missions_completed = 0
        self.missions_failed = 0
    
    def recruit(self, system_prompt: str = "", rank: Rank = Rank.RECRUIT) -> Soldier:
        s = Soldier(specialty=self.specialty, rank=rank, system_prompt=system_prompt)
        self.soldiers.append(s)
        logger.info(f"Brigade {self.name}: recruited {s.id}")
        return s
    
    def get_best_soldier(self, min_rank: Optional[Rank] = None) -> Optional[Soldier]:
        candidates = self.soldiers
        if min_rank:
            candidates = [s for s in candidates if s.rank.value >= min_rank.value]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.stats.trust_score)
    
    def get_available_soldiers(self, min_trust: float = 0.3) -> List[Soldier]:
        return [s for s in self.soldiers if s.stats.trust_score >= min_trust]
    
    def stats(self) -> Dict[str, Any]:
        if not self.soldiers:
            return {"name": self.name, "count": 0}
        return {
            "name": self.name,
            "specialty": self.specialty,
            "count": len(self.soldiers),
            "avg_trust": round(sum(s.stats.trust_score for s in self.soldiers) / len(self.soldiers), 3),
            "missions_completed": self.missions_completed,
            "missions_failed": self.missions_failed,
            "top_soldier": self.get_best_soldier().id if self.soldiers else None,
        }
