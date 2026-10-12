"""Soldier - وكيل بعزلة كاملة وهوية فريدة."""
import uuid
import hashlib
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

from novamind.core.company.ranks import Rank, can_promote

logger = logging.getLogger("Soldier")

@dataclass
class SoldierStats:
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_time: float = 0.0
    trust_score: float = 0.5
    hallucination_events: int = 0

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 0.0

    @property
    def avg_time(self) -> float:
        return self.total_time / self.tasks_completed if self.tasks_completed else 0.0


class Soldier:
    """جندي رقمي: هوية فريدة + عزل + رتبة + إحصائيات."""
    
    def __init__(
        self,
        specialty: str,
        rank: Rank = Rank.RECRUIT,
        system_prompt: str = "",
        mission: str = "",
    ):
        self.id = f"SOL-{uuid.uuid4().hex[:8].upper()}"
        self.specialty = specialty
        self.rank = rank
        self.system_prompt = system_prompt
        self.mission = mission
        self.stats = SoldierStats()
        self.created_at = datetime.now()
        self.history: List[Dict] = []
        self._isolated_context: Dict[str, Any] = {}  # سياق خاص به فقط
        
        # HMAC signature للهوية
        self.signature = hashlib.sha256(
            f"{self.id}:{specialty}:{self.created_at.isoformat()}".encode()
        ).hexdigest()[:16]
        
        logger.info(f"Created {self.id} ({specialty}, rank={rank.name})")
    
    def get_identity(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "specialty": self.specialty,
            "rank": self.rank.name,
            "rank_level": self.rank.value,
            "signature": self.signature,
            "stats": {
                "tasks": self.stats.tasks_completed,
                "failed": self.stats.tasks_failed,
                "success_rate": round(self.stats.success_rate, 3),
                "trust": round(self.stats.trust_score, 3),
                "hallucinations": self.stats.hallucination_events,
            },
        }
    
    def record_task(self, success: bool, duration: float, hallucination: bool = False):
        if success:
            self.stats.tasks_completed += 1
            self.stats.trust_score = min(1.0, self.stats.trust_score + 0.02)
        else:
            self.stats.tasks_failed += 1
            self.stats.trust_score = max(0.0, self.stats.trust_score - 0.05)
        
        if hallucination:
            self.stats.hallucination_events += 1
            self.stats.trust_score = max(0.0, self.stats.trust_score - 0.10)
        
        self.stats.total_time += duration
        self.history.append({
            "success": success,
            "duration": round(duration, 2),
            "hallucination": hallucination,
            "time": datetime.now().isoformat(),
        })
    
    def check_promotion(self) -> bool:
        return can_promote(
            self.rank,
            self.stats.tasks_completed,
            self.stats.success_rate,
            self.stats.trust_score,
        )
    
    def promote(self) -> bool:
        if self.check_promotion() and self.rank.value < Rank.COMMANDANT.value:
            old = self.rank.name
            self.rank = Rank(self.rank.value + 1)
            logger.info(f"{self.id} promoted {old} → {self.rank.name}")
            return True
        return False
    
    def demote(self) -> bool:
        if self.rank.value > Rank.RECRUIT.value:
            old = self.rank.name
            self.rank = Rank(self.rank.value - 1)
            logger.warning(f"{self.id} demoted {old} → {self.rank.name}")
            return True
        return False
