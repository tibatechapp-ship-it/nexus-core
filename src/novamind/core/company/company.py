"""NovaMind Company - الشركة الرقمية الكاملة."""
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional

from novamind.core.company.soldier import Soldier
from novamind.core.company.brigade import Brigade
from novamind.core.company.ranks import Rank
from novamind.core.company.memory import CompanyMemory
from novamind.core.company.vaccination import Vaccination
from novamind.core.company.audit import AuditTrail
from novamind.core.company.hallucination import HallucinationDetector
from novamind.core.company.academy import Academy
from novamind.core.company.assessment import AssessmentCenter
from novamind.core.company.monitoring import Monitor
from novamind.core.company.command import HighCommand
from novamind.core.llm_router import LLMRouter

logger = logging.getLogger("Company")


class NovaMindCompany:
    """الشركة الكاملة: تصنع، تدرّب، تقيّم، تطعّم، تراقب."""
    
    def __init__(self, llm_router: Optional[LLMRouter] = None):
        self.llm = llm_router or LLMRouter()
        self.memory = CompanyMemory()
        self.vaccination = Vaccination()
        self.audit = AuditTrail()
        self.hallucination = HallucinationDetector()
        self.academy = Academy(llm_router=self.llm)
        self.assessment = AssessmentCenter(audit=self.audit)
        self.monitor = Monitor()
        self.command = HighCommand(audit=self.audit, monitor=self.monitor)
        
        self.stats = {
            "soldiers_created": 0,
            "missions_run": 0,
            "missions_success": 0,
            "missions_failed": 0,
            "vaccines_produced": 0,
            "hallucinations_caught": 0,
        }
    
    async def recruit(
        self,
        specialty: str,
        system_prompt: str = "",
        training_missions: int = 2,
    ) -> Dict[str, Any]:
        """يصنع جندياً ويدرّبه."""
        # 1. تدريب
        result = await self.academy.train_soldier(
            specialty=specialty,
            system_prompt=system_prompt,
            missions=training_missions,
        )
        soldier = result["soldier"]
        
        # 2. أضفه لكتيبة
        if specialty not in self.command.brigades:
            self.command.register_brigade(Brigade(specialty.title(), specialty))
        self.command.brigades[specialty.title()].soldiers.append(soldier)
        
        # 3. سجّل في audit
        self.audit.record("recruit", "academy", {
            "soldier_id": soldier.id,
            "specialty": specialty,
        })
        
        self.stats["soldiers_created"] += 1
        
        return {
            "soldier_id": soldier.id,
            "identity": soldier.get_identity(),
            "training": result["training_log"],
        }
    
    async def execute_mission(
        self,
        specialty: str,
        task: str,
        timeout: float = 180.0,
    ) -> Dict[str, Any]:
        """ينفذ مهمة عبر أفضل جندي متاح."""
        # 1. اختر جندياً
        soldier = self.command.assign_mission(specialty, task)
        if not soldier:
            return {"status": "no_soldier", "specialty": specialty}
        
        # 2. تحقق من الذاكرة
        cached = self.memory.get_best_response(specialty, task)
        
        # 3. نفّذ
        t0 = time.time()
        try:
            response = await asyncio.wait_for(
                self.llm.generate(task, system_prompt=soldier.system_prompt),
                timeout=timeout,
            )
            dt = time.time() - t0
            
            # 4. كشف الهلوسة
            h_check = self.hallucination.check(response, task)
            if h_check["is_hallucination"]:
                self.stats["hallucinations_caught"] += 1
                soldier.record_task(success=False, duration=dt, hallucination=True)
                self.audit.record("hallucination_detected", soldier.id, h_check)
                
                # إنتاج تطعيم
                self.vaccination.produce_vaccine(
                    specialty=specialty,
                    threat=task[:200],
                    defense=h_check["issues"][:5],
                    discovered_by=soldier.id,
                )
                self.stats["vaccines_produced"] += 1
                
                return {
                    "status": "hallucination",
                    "soldier_id": soldier.id,
                    "hallucination": h_check,
                    "response": response[:200],
                }
            
            # 5. نجح
            soldier.record_task(success=True, duration=dt)
            self.stats["missions_run"] += 1
            self.stats["missions_success"] += 1
            
            # 6. حفظ درس
            self.memory.record_lesson(
                specialty=specialty,
                task=task,
                response=response,
                success=True,
                agent_id=soldier.id,
            )
            
            self.audit.record("mission_success", soldier.id, {
                "specialty": specialty,
                "duration": round(dt, 2),
            })
            
            return {
                "status": "success",
                "soldier_id": soldier.id,
                "response": response,
                "time": round(dt, 2),
                "hallucination": h_check,
            }
        
        except asyncio.TimeoutError:
            soldier.record_task(success=False, duration=timeout)
            self.stats["missions_run"] += 1
            self.stats["missions_failed"] += 1
            self.audit.record("mission_timeout", soldier.id, {"task": task[:200]})
            return {"status": "timeout", "soldier_id": soldier.id}
        
        except Exception as e:
            soldier.record_task(success=False, duration=time.time() - t0)
            self.stats["missions_run"] += 1
            self.stats["missions_failed"] += 1
            self.audit.record("mission_error", soldier.id, {"error": str(e)})
            return {"status": "error", "error": str(e)}
    
    def review_all(self) -> Dict[str, Any]:
        """يراجع كل الجنود — ترقية/تخفيض."""
        all_soldiers = []
        for b in self.command.brigades.values():
            all_soldiers.extend(b.soldiers)
        return self.assessment.evaluate_brigade(all_soldiers)
    
    def full_report(self) -> Dict[str, Any]:
        """تقرير شامل عن الشركة."""
        return {
            "stats": self.stats,
            "memory": self.memory.stats(),
            "vaccination": self.vaccination.stats(),
            "audit": self.audit.verify_chain(),
            "command": self.command.status_report(),
        }
    
    async def close(self):
        await self.academy.close()
        await self.llm.close()
