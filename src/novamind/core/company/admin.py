"""Admin Commands - أوامر تطوير الوكلاء."""
import asyncio
import logging
from typing import Dict, List, Any

logger = logging.getLogger("Admin")


class AdminCommands:
    """أوامر إدارية لتطوير الوكلاء."""
    
    def __init__(self, supreme):
        self.supreme = supreme
    
    def develop_soldier(self, soldier_id: str, new_specialty: str = None,
                        new_prompt: str = None) -> Dict[str, Any]:
        """يطوّر جندياً: تغيير تخصص أو prompt أو رتبة."""
        soldier = next((s for s in self.supreme.soldiers if s.id == soldier_id), None)
        if not soldier:
            return {"status": "not_found", "soldier_id": soldier_id}
        
        changes = []
        if new_specialty and new_specialty != soldier.specialty:
            old = soldier.specialty
            soldier.specialty = new_specialty
            changes.append(f"specialty: {old} → {new_specialty}")
        
        if new_prompt:
            soldier.system_prompt = new_prompt
            changes.append("system_prompt updated")
        
        self.supreme.registry.save(soldier)
        self.supreme.audit.record("develop", soldier_id, {"changes": changes})
        
        return {"status": "developed", "soldier_id": soldier_id, "changes": changes}
    
    def upgrade_soldier(self, soldier_id: str) -> Dict[str, Any]:
        """يرقّي جندياً يدوياً (يتجاوز الشروط)."""
        soldier = next((s for s in self.supreme.soldiers if s.id == soldier_id), None)
        if not soldier:
            return {"status": "not_found"}
        
        from novamind.core.company.ranks import Rank
        if soldier.rank.value >= Rank.COMMANDANT.value:
            return {"status": "max_rank", "rank": soldier.rank.name}
        
        old = soldier.rank.name
        soldier.rank = Rank(soldier.rank.value + 1)
        self.supreme.registry.save(soldier)
        self.supreme.audit.record("manual_promote", soldier_id, {
            "from": old, "to": soldier.rank.name
        })
        
        return {"status": "promoted", "from": old, "to": soldier.rank.name}
    
    def retrain_soldier(self, soldier_id: str) -> Dict[str, Any]:
        """يعيد تدريب جندي (reset stats + صياغة جديدة)."""
        soldier = next((s for s in self.supreme.soldiers if s.id == soldier_id), None)
        if not soldier:
            return {"status": "not_found"}
        
        # احفظ في History قبل reset
        old_stats = dict(soldier.stats.__dict__)
        
        # reset
        soldier.stats.tasks_completed = 0
        soldier.stats.tasks_failed = 0
        soldier.stats.total_time = 0.0
        soldier.stats.trust_score = 0.5
        soldier.stats.hallucination_events = 0
        
        self.supreme.registry.save(soldier)
        self.supreme.audit.record("retrain", soldier_id, {"old_stats": old_stats})
        
        return {"status": "retrained", "soldier_id": soldier_id}
    
    def inject_vaccine(self, specialty: str, threat: str, defense: str) -> Dict[str, Any]:
        """يحقن تطعيماً في النظام."""
        result = self.supreme.vaccination.produce_vaccine(
            specialty=specialty,
            threat=threat,
            defense=defense,
            discovered_by="admin",
        )
        self.supreme.audit.record("manual_vaccine", "admin", result)
        return {"status": "injected", "vaccine": result}
    
    def inject_lesson(self, specialty: str, task: str, response: str) -> Dict[str, Any]:
        """يحقن درساً في الذاكرة."""
        self.supreme.memory.record_lesson(
            specialty=specialty,
            task=task,
            response=response,
            success=True,
            agent_id="admin",
        )
        return {"status": "injected", "specialty": specialty}
    
    def suspend_soldier(self, soldier_id: str) -> Dict[str, Any]:
        """يوقف جندياً مؤقتاً."""
        soldier = next((s for s in self.supreme.soldiers if s.id == soldier_id), None)
        if not soldier:
            return {"status": "not_found"}
        self.supreme.registry.mark_status(soldier_id, "suspended")
        return {"status": "suspended", "soldier_id": soldier_id}
    
    def revive_soldier(self, soldier_id: str) -> Dict[str, Any]:
        """يعيد تفعيل جندي موقوف."""
        self.supreme.registry.mark_status(soldier_id, "active")
        return {"status": "revived", "soldier_id": soldier_id}
    
    def purge_weak(self, min_trust: float = 0.3) -> Dict[str, Any]:
        """يستبعد الجنود الضعفاء."""
        weak = [s for s in self.supreme.soldiers if s.stats.trust_score < min_trust]
        for s in weak:
            self.supreme.registry.mark_status(s.id, "exiled")
            self.supreme.sandbox.cleanup(s.id)
        
        self.supreme.soldiers = [s for s in self.supreme.soldiers if s.stats.trust_score >= min_trust]
        self.supreme.registry.save_batch(self.supreme.soldiers)
        self.supreme.audit.record("purge", "admin", {"count": len(weak)})
        
        return {"status": "purged", "count": len(weak), "remaining": len(self.supreme.soldiers)}
    
    def clone_elite(self, soldier_id: str, count: int = 3) -> Dict[str, Any]:
        """يستنسخ جندياً نخبوياً."""
        soldier = next((s for s in self.supreme.soldiers if s.id == soldier_id), None)
        if not soldier:
            return {"status": "not_found"}
        
        from novamind.core.company.soldier import Soldier
        clones = []
        for i in range(count):
            clone = Soldier(
                specialty=soldier.specialty,
                rank=soldier.rank,
                system_prompt=soldier.system_prompt,
                mission=f"Clone of {soldier_id}",
            )
            self.supreme.soldiers.append(clone)
            self.supreme.registry.save(clone)
            self.supreme.barracks.recruit_to_barracks(clone)
            self.supreme.sandbox.create(clone.id)
            clones.append(clone.id)
        
        self.supreme.audit.record("clone_elite", soldier_id, {"clones": clones})
        return {"status": "cloned", "source": soldier_id, "clones": clones}
