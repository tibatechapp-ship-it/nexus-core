"""Barracks System - كل 10 جنود في ثكنة يتشاركون المعرفة."""
import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from novamind.core.company.soldier import Soldier

logger = logging.getLogger("Barracks")


@dataclass
class Barracks:
    """ثكنة: 5-15 جندياً يتشاركون الذاكرة والتعاون."""
    id: str
    name: str
    specialty: str
    max_size: int = 10
    soldiers: List[Soldier] = field(default_factory=list)
    shared_memory: Dict[str, Any] = field(default_factory=dict)
    local_vaccines: List[Dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    victories: int = 0
    defeats: int = 0

    def is_full(self) -> bool:
        return len(self.soldiers) >= self.max_size

    def assign(self, soldier: Soldier) -> bool:
        """يضيف جندياً إلى الثكنة."""
        if self.is_full():
            logger.warning(f"Barracks {self.id} is full")
            return False
        if soldier.specialty != self.specialty:
            logger.warning(f"Soldier specialty {soldier.specialty} != barrack {self.specialty}")
            return False
        self.soldiers.append(soldier)
        logger.info(f"Barracks {self.id}: +1 soldier ({soldier.id})")
        return True

    def share_lesson(self, lesson_key: str, lesson_value: Any, source_id: str):
        """يشارك درساً مع الثكنة كلها."""
        self.shared_memory[lesson_key] = {
            "value": lesson_value,
            "source": source_id,
            "time": time.time(),
        }
        logger.info(f"Barracks {self.id}: shared lesson '{lesson_key}' by {source_id}")

    def get_shared(self, lesson_key: str) -> Optional[Any]:
        """يجلب درساً مشتركاً."""
        entry = self.shared_memory.get(lesson_key)
        return entry["value"] if entry else None

    def local_vaccine(self, threat: str, defense: str, discovered_by: str):
        """ينتج تطعيماً محلياً للثكنة."""
        self.local_vaccines.append({
            "threat": threat[:300],
            "defense": defense[:500],
            "discovered_by": discovered_by,
            "time": time.time(),
        })
        logger.info(f"Barracks {self.id}: local vaccine for '{threat[:40]}'")

    def avg_trust(self) -> float:
        if not self.soldiers:
            return 0.0
        return sum(s.stats.trust_score for s in self.soldiers) / len(self.soldiers)

    def avg_success_rate(self) -> float:
        if not self.soldiers:
            return 0.0
        return sum(s.stats.success_rate for s in self.soldiers) / len(self.soldiers)

    def status(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "specialty": self.specialty,
            "size": len(self.soldiers),
            "max_size": self.max_size,
            "avg_trust": round(self.avg_trust(), 3),
            "avg_success_rate": round(self.avg_success_rate(), 3),
            "shared_lessons": len(self.shared_memory),
            "local_vaccines": len(self.local_vaccines),
            "victories": self.victories,
            "defeats": self.defeats,
        }


class BarracksManager:
    """مدير الثكنات: يوزّع الجنود، ينشئ ثكنات جديدة، يقارن أدائها."""
    
    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self.barracks: Dict[str, Barracks] = {}
        self.counter = 0

    def _new_id(self) -> str:
        self.counter += 1
        return f"BRK-{self.counter:03d}"

    def recruit_to_barracks(self, soldier: Soldier) -> Barracks:
        """يضيف جندياً لأفضل ثكنة متاحة."""
        # ابحث عن ثكنة مناسبة (نفس التخصص، ليست ممتلئة)
        for b in self.barracks.values():
            if b.specialty == soldier.specialty and not b.is_full():
                b.assign(soldier)
                return b
        
        # أنشئ ثكنة جديدة
        new_barracks = Barracks(
            id=self._new_id(),
            name=f"{soldier.specialty.title()} Barracks {self.counter}",
            specialty=soldier.specialty,
            max_size=self.max_size,
        )
        new_barracks.assign(soldier)
        self.barracks[new_barracks.id] = new_barracks
        logger.info(f"New barracks: {new_barracks.id}")
        return new_barracks

    def broadcast_lesson(self, specialty: str, lesson_key: str, lesson_value: Any, source_id: str):
        """ينشر درساً لكل ثكنات تخصص معين."""
        for b in self.barracks.values():
            if b.specialty == specialty:
                b.share_lesson(lesson_key, lesson_value, source_id)

    def get_rankings(self) -> List[Dict]:
        """يرتّب الثكنات حسب أدائها."""
        rankings = []
        for b in self.barracks.values():
            rankings.append({
                "id": b.id,
                "name": b.name,
                "score": (b.avg_trust() * 0.6 + b.avg_success_rate() * 0.4),
                **b.status(),
            })
        rankings.sort(key=lambda x: x["score"], reverse=True)
        return rankings

    def best_barracks(self) -> Optional[Barracks]:
        """أفضل ثكنة."""
        if not self.barracks:
            return None
        return max(self.barracks.values(), key=lambda b: b.avg_trust() * 0.6 + b.avg_success_rate() * 0.4)

    def worst_barracks(self) -> Optional[Barracks]:
        """أسوأ ثكنة."""
        if not self.barracks:
            return None
        return min(self.barracks.values(), key=lambda b: b.avg_trust() * 0.6 + b.avg_success_rate() * 0.4)

    def stats(self) -> Dict[str, Any]:
        return {
            "total_barracks": len(self.barracks),
            "total_soldiers": sum(len(b.soldiers) for b in self.barracks.values()),
            "by_specialty": self._count_by_specialty(),
        }

    def _count_by_specialty(self) -> Dict[str, int]:
        counts = {}
        for b in self.barracks.values():
            counts[b.specialty] = counts.get(b.specialty, 0) + len(b.soldiers)
        return counts
