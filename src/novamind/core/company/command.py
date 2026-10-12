"""High Command - القيادة العليا للشركة."""
import logging
from typing import Dict, Any, List, Optional

from novamind.core.company.soldier import Soldier
from novamind.core.company.brigade import Brigade
from novamind.core.company.ranks import Rank
from novamind.core.company.audit import AuditTrail
from novamind.core.company.monitoring import Monitor

logger = logging.getLogger("Command")

class HighCommand:
    """القيادة: تدير الكتائب، تكلف المهام، تشرف على الأداء."""
    
    def __init__(self, audit: AuditTrail = None, monitor: Monitor = None):
        self.audit = audit or AuditTrail()
        self.monitor = monitor or Monitor()
        self.brigades: Dict[str, Brigade] = {}
        self.commander: Optional[Soldier] = None
        self.deputies: List[Soldier] = []
    
    def register_brigade(self, brigade: Brigade):
        """يسجّل كتيبة."""
        self.brigades[brigade.name] = brigade
        logger.info(f"Registered brigade: {brigade.name}")
        self.audit.record("brigade_register", "high_command", {
            "name": brigade.name,
            "specialty": brigade.specialty,
            "soldiers": len(brigade.soldiers),
        })
    
    def appoint_commander(self, soldier: Soldier):
        """يعيّن قائداً أعلى."""
        self.commander = soldier
        logger.info(f"Commander appointed: {soldier.id}")
        self.audit.record("commander_appointed", "high_command", {
            "soldier_id": soldier.id,
            "rank": soldier.rank.name,
        })
    
    def appoint_deputy(self, soldier: Soldier):
        """يعيّن نائباً."""
        self.deputies.append(soldier)
        self.audit.record("deputy_appointed", "high_command", {
            "soldier_id": soldier.id,
        })
    
    def assign_mission(
        self,
        specialty: str,
        task: str,
        min_trust: float = 0.3,
    ) -> Optional[Soldier]:
        """يكلّف أفضل جندي متاح بمهمة."""
        best = None
        best_trust = min_trust
        
        for name, brigade in self.brigades.items():
            if brigade.specialty != specialty:
                continue
            candidates = [s for s in brigade.soldiers if s.stats.trust_score >= min_trust]
            for c in candidates:
                if c.stats.trust_score > best_trust:
                    best_trust = c.stats.trust_score
                    best = c
        
        if best:
            self.audit.record("mission_assigned", best.id, {
                "specialty": specialty,
                "task": task[:200],
                "trust": best.stats.trust_score,
            })
        return best
    
    def status_report(self) -> Dict[str, Any]:
        """تقرير كامل عن الشركة."""
        all_soldiers = []
        for b in self.brigades.values():
            all_soldiers.extend(b.soldiers)
        
        health = self.monitor.check_health(all_soldiers, list(self.brigades.values()))
        
        return {
            "commander": self.commander.get_identity() if self.commander else None,
            "deputies": [d.get_identity() for d in self.deputies],
            "brigades": {name: b.stats() for name, b in self.brigades.items()},
            "health": health,
            "audit_valid": self.audit.verify_chain()["valid"],
        }
