"""Supreme Council - يدمج كل الطبقات."""
import asyncio
import logging
import time
from typing import Dict, List, Any, Optional

from novamind.core.company.soldier import Soldier
from novamind.core.company.ranks import Rank
from novamind.core.company.constitution import Constitution
from novamind.core.company.genome import ErrorGenome
from novamind.core.company.reputation import ReputationBank
from novamind.core.company.consensus import ConsensusVote
from novamind.core.company.radar import ThreatRadar
from novamind.core.company.darwinian import DarwinianEngine
from novamind.core.company.barracks import BarracksManager
from novamind.core.company.audit import AuditTrail
from novamind.core.company.memory import CompanyMemory
from novamind.core.company.vaccination import Vaccination
from novamind.core.company.hallucination import HallucinationDetector
from novamind.core.company.registry import SoldierRegistry
from novamind.core.company.sandbox import SoldierSandbox
from novamind.core.company.cost_tracker import CostTracker
from novamind.core.company.targets import DailyTargetSystem
from novamind.core.company.tech_targets import TechTargetSystem
from novamind.core.llm_router import LLMRouter
from novamind.core.redis_client import get_redis
from novamind.core.memory_rag import SimpleRAG

logger = logging.getLogger("Supreme")


class SupremeCouncil:
    def __init__(self, llm_router: Optional[LLMRouter] = None, verbose: bool = True):
        self.llm = llm_router or LLMRouter()
        self.verbose = verbose
        # 7 طبقات
        self.constitution = Constitution()
        self.genome = ErrorGenome()
        self.bank = ReputationBank()
        self.consensus = ConsensusVote(llm_router=self.llm)
        self.radar = ThreatRadar()
        self.darwinian = DarwinianEngine()
        self.barracks = BarracksManager()
        # أساسية
        self.audit = AuditTrail()
        self.memory = CompanyMemory()
        self.vaccination = Vaccination()
        self.hallucination = HallucinationDetector()
        # حرجة
        self.registry = SoldierRegistry()
        self.sandbox = SoldierSandbox()
        self.costs = CostTracker()
        self.targets = DailyTargetSystem()
        self.tech_targets = TechTargetSystem()
        self.redis = None  # lazy init
        self.rag = SimpleRAG()
        # حالة
        self.soldiers: List[Soldier] = []
        self.stats = {
            "missions_total": 0, "missions_success": 0,
            "missions_failed": 0, "missions_blocked": 0,
            "hallucinations": 0, "vaccines": 0, "evolutions": 0,
        }

    async def init_redis(self):
        """يهيّئ Redis."""
        try:
            self.redis = await get_redis()
            self._log(f"Redis: {'connected' if self.redis.available else 'fallback'}")
        except Exception as e:
            self._log(f"Redis init failed: {e}")
            self.redis = None

    def _log(self, msg):
        if self.verbose:
            print(f"[Supreme] {msg}")
        logger.info(msg)

    def recruit(self, specialty: str, system_prompt: str = "") -> Dict[str, Any]:
        soldier = Soldier(
            specialty=specialty, rank=Rank.PRIVATE,
            system_prompt=system_prompt or f"You are a {specialty}.",
        )
        self.bank.open_account(soldier.id, initial=50)
        self.registry.save(soldier)
        barrack = self.barracks.recruit_to_barracks(soldier)
        self.sandbox.create(soldier.id)
        self.soldiers.append(soldier)
        self.audit.record("recruit", "supreme_council", {
            "soldier_id": soldier.id, "specialty": specialty, "barrack_id": barrack.id,
        })
        self._log(f"جنّدنا {soldier.id} ({specialty})")
        return soldier.get_identity()

    def restore_from_registry(self) -> int:
        soldiers = self.registry.load_all(status="active")
        self.soldiers = soldiers
        for s in soldiers:
            if not self.sandbox.exists(s.id):
                self.sandbox.create(s.id)
        self._log(f"استعدنا {len(soldiers)} جندياً")
        return len(soldiers)

    def get_daily_missions(self, soldier_id: str) -> List[Dict]:
        soldier = next((s for s in self.soldiers if s.id == soldier_id), None)
        if not soldier:
            return []
        missions = self.tech_targets.get_daily_mission_set(
            soldier.specialty, soldier.rank.value, count=5,
        )
        return [{
            "mission_id": m["id"], "task": m["task"],
            "verify_criteria": m.get("verify", ""),
            "assigned_to": soldier_id, "specialty": soldier.specialty,
        } for m in missions]

    async def execute_mission_reflective(
        self,
        specialty: str,
        task: str,
    ) -> Dict[str, Any]:
        """ينفذ مهمة عبر Reflective RAG (6 مراحل)."""
        self.stats["missions_total"] = self.stats.get("missions_total", 0) + 1
        
        # اختر جندياً
        available = [s for s in self.soldiers if s.specialty == specialty]
        if not available:
            self.recruit(specialty)
            available = [s for s in self.soldiers if s.specialty == specialty]
        soldier = max(available, key=lambda s: s.stats.trust_score)
        
        # RAG
        result = await self.reflective_rag.execute(
            task=task,
            system_prompt=soldier.system_prompt,
            specialty=specialty,
        )
        
        # سجّل
        success = result["status"] == "success"
        if success:
            soldier.record_task(True, result["time"])
            self.bank.reward(soldier.id, "task_success", task[:100])
            self.stats["missions_success"] = self.stats.get("missions_success", 0) + 1
        else:
            soldier.record_task(False, result["time"])
            self.stats["missions_failed"] = self.stats.get("missions_failed", 0) + 1
        
        self.registry.save(soldier)
        self.audit.record("reflective_mission", soldier.id, {
            "specialty": specialty,
            "success": success,
            "rag_hits": result.get("rag_hits", 0),
        })
        
        return result

    async def execute_mission(self, specialty: str, task: str) -> Dict[str, Any]:
        self.stats["missions_total"] += 1
        radar = self.radar.scan(task, specialty)
        if radar["decision"] == "BLOCK":
            self.stats["missions_blocked"] += 1
            return {"status": "blocked", "radar": radar}
        const = self.constitution.check_action(task)
        if not const["allowed"]:
            return {"status": "constitution_violation", "violations": const["violations"]}

        available = [s for s in self.soldiers if s.specialty == specialty]
        if not available:
            self.recruit(specialty)
            available = [s for s in self.soldiers if s.specialty == specialty]
        soldier = max(available, key=lambda s: s.stats.trust_score)

        t0 = time.time()
        try:
            # ═══ RAG: استرجع دروس مشابهة ═══
            similar = self.rag.find_similar(specialty, task, top_k=3)
            augmented_prompt = task
            if similar:
                lessons_text = "\n\n## PAST LESSONS:\n"
                for i, lesson in enumerate(similar, 1):
                    lessons_text += f"\n### Lesson {i}:\nTask: {lesson['task'][:200]}\nResponse: {lesson['response'][:300]}\n"
                augmented_prompt = f"{task}\n\n{lessons_text}"
                self._log(f"RAG: injected {len(similar)} lessons")
            
            # ═══ التنفيذ الأول ═══
            response = await asyncio.wait_for(
                self.llm.generate(augmented_prompt, system_prompt=soldier.system_prompt),
                timeout=180.0,
            )
            
            # ═══ Feedback: فحص Constitution ═══
            const_check = self.constitution.check_action(response)
            if not const_check["allowed"]:
                self._log(f"Constitution violated: {const_check['violations']}")
                response = await asyncio.wait_for(
                    self.llm.generate(
                        f"{augmented_prompt}\n\nYour previous output violated: {const_check['violations']}. Rewrite following all laws.",
                        system_prompt=soldier.system_prompt,
                    ),
                    timeout=180.0,
                )
            
            dt = time.time() - t0
            h_check = self.hallucination.check(response, task)
            if h_check["is_hallucination"]:
                self.stats["hallucinations"] += 1
                soldier.record_task(False, dt, hallucination=True)
                self.bank.penalize(soldier.id, "hallucination", task[:100])
                self.targets.record_task(soldier.id, specialty, False, dt, True)
                self.genome.register_error(specialty, "hallucination",
                    task[:200], str(h_check["issues"]), soldier.id)
                self.vaccination.produce_vaccine(specialty, task[:200],
                    str(h_check["issues"])[:500], soldier.id)
                self.stats["vaccines"] += 1
                self.registry.save(soldier)
                return {"status": "hallucination", "soldier_id": soldier.id,
                        "hallucination": h_check}

            soldier.record_task(True, dt)
            self.bank.reward(soldier.id, "task_success", task[:100])
            self.rag.record(specialty, task, response, True)
            self.targets.record_task(soldier.id, specialty, True, dt, False)
            self.stats["missions_success"] += 1
            self.costs.record(soldier.id, specialty, "ollama-qwen-local", task, response)
            self.memory.record_lesson(specialty, task, response, True, soldier.id)
            for b in self.barracks.barracks.values():
                if b.specialty == specialty:
                    b.share_lesson(f"s_{hash(task[:30])}", response[:300], soldier.id)
            self.registry.save(soldier)
            self.audit.record("mission_success", soldier.id, {
                "specialty": specialty, "duration": round(dt, 2),
            })
            return {"status": "success", "soldier_id": soldier.id,
                    "response": response, "time": round(dt, 2),
                    "hallucination": h_check, "radar": radar}
        except Exception as e:
            self.stats["missions_failed"] += 1
            soldier.record_task(False, time.time() - t0)
            self.bank.penalize(soldier.id, "task_failure", str(e)[:100])
            self.targets.record_task(soldier.id, specialty, False, time.time() - t0, False)
            self.registry.save(soldier)
            self.audit.record("mission_error", soldier.id, {"error": str(e)[:200]})
            return {"status": "error", "error": str(e)[:200]}

    async def execute_daily_target(self, soldier_id: str) -> Dict[str, Any]:
        missions = self.get_daily_missions(soldier_id)
        if not missions:
            return {"status": "no_missions"}
        m = missions[0]
        result = await self.execute_mission(m["specialty"], m["task"])
        result["mission_id"] = m["mission_id"]
        result["verify_criteria"] = m["verify_criteria"]
        return result

    def evolve(self) -> Dict[str, Any]:
        result = self.darwinian.evolve(self.soldiers, bank=self.bank)
        if result["status"] == "evolved":
            self.stats["evolutions"] += 1
            for clone in result.get("clones", []):
                self.soldiers.append(clone)
                self.registry.save(clone)
                self.barracks.recruit_to_barracks(clone)
                self.sandbox.create(clone.id)
            self.registry.save_batch(self.soldiers)
        return result

    def evaluate_daily_targets(self) -> Dict[str, Any]:
        result = self.targets.evaluate_all(self.soldiers)
        for detail in result["details"]:
            sid = detail["soldier_id"]
            delta = detail["coins_delta"]
            acc = self.bank.get_account(sid)
            if acc and delta != 0:
                acc["balance"] += delta
            self.audit.record("daily_eval", sid, detail)
        return result

    def full_report(self) -> Dict[str, Any]:
        return {
            "stats": self.stats,
            "soldiers_count": len(self.soldiers),
            "registry": self.registry.get_stats(),
            "sandbox": self.sandbox.stats(),
            "costs": self.costs.stats(),
            "daily_targets": self.targets.stats(),
            "barracks": self.barracks.stats(),
            "reputation": self.bank.stats(),
            "genome": self.genome.stats(),
            "vaccination": self.vaccination.stats(),
            "memory": self.memory.stats(),
            "radar": self.radar.stats(),
            "audit": self.audit.verify_chain(),
            "constitution_valid": self.constitution.verify_all(),
            "consensus": self.consensus.stats(),
            "darwinian": self.darwinian.stats(),
        }

    async def close(self):
        self.registry.save_batch(self.soldiers)
        await self.consensus.close()
        await self.llm.close()
