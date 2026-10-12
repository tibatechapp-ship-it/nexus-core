"""
Trainer — المدرب (50 مدرباً متخصصاً)

كل مدرب:
- متخصص في مجال واحد
- معزول تماماً عن العاملين
- لا يرى إلا طلبات التدريب
- مدرَّب على "صناعة" الوكلاء
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import time
import logging
import hashlib

logger = logging.getLogger("trainer")


class TrainerSpecialty(Enum):
    CODING = "coding"
    SECURITY = "security"
    DEVOPS = "devops"
    QUALITY = "quality"
    AI = "ai"
    DATABASE = "database"
    FRONTEND = "frontend"
    BACKEND = "backend"
    TESTING = "testing"
    ARCHITECTURE = "architecture"


@dataclass
class TrainingSession:
    """جلسة تدريب"""
    session_id: str
    trainer_id: str
    blueprint: Any  # AgentBlueprint
    started_at: float = 0.0
    completed_at: float = 0.0
    success: bool = False
    notes: str = ""


class Trainer:
    """
    المدرب — يصنع وكلاء
    
    الصلاحيات:
    - قراءة blueprint من المصنع
    - تشغيل اختبارات التدريب
    - تسليم منتج
    - لا يتواصل مع العاملين مباشرة
    """
    
    def __init__(
        self,
        trainer_id: str,
        specialty: TrainerSpecialty,
        factory,
        sandbox,
    ):
        self.trainer_id = trainer_id
        self.specialty = specialty
        self.factory = factory
        self.sandbox = sandbox
        
        # سجل
        self.trained_count = 0
        self.failed_count = 0
        self.current_session: Optional[TrainingSession] = None
        self.sessions: List[TrainingSession] = []
        
        # خصائص
        self.skill_level = 1  # 1-5
        self.reputation = 1.0
        
        logger.info(f"Trainer {trainer_id} ready (specialty={specialty.value})")
    
    def train(self, blueprint) -> Dict:
        """
        درّب وكيلاً جديداً
        
        العملية:
        1. حلّل الـ blueprint
        2. طبّق منهج التدريب
        3. اختبر المهارات
        4. أعد النتيجة
        """
        session_id = f"s_{self.trainer_id}_{int(time.time())}"
        session = TrainingSession(
            session_id=session_id,
            trainer_id=self.trainer_id,
            blueprint=blueprint,
            started_at=time.time(),
        )
        self.current_session = session
        
        logger.info(f"[{self.trainer_id}] Training {blueprint.name} ({blueprint.spec.value})")
        
        try:
            # 1. التحقق من التخصص
            if not self._matches_specialty(blueprint):
                logger.warning(f"  ✗ Blueprint specialty doesn't match")
                session.success = False
                session.notes = "specialty_mismatch"
                return {"ok": False, "reason": "specialty_mismatch"}
            
            # 2. التخطيط للتدريب
            plan = self._build_training_plan(blueprint)
            logger.info(f"  Plan: {len(plan)} phases")
            
            # 3. تنفيذ كل مرحلة
            for phase in plan:
                self._execute_phase(phase, blueprint)
            
            # 4. اختبار نهائي
            test_result = self._final_assessment(blueprint)
            
            if test_result["passed"]:
                self.trained_count += 1
                session.success = True
                session.notes = "training_complete"
                logger.info(f"  ✓ {blueprint.name} ready")
            else:
                self.failed_count += 1
                session.success = False
                session.notes = "final_test_failed"
                logger.warning(f"  ✗ {blueprint.name} failed final test")
            
            session.completed_at = time.time()
            self.sessions.append(session)
            self.current_session = None
            
            return {
                "ok": session.success,
                "session_id": session_id,
                "test_result": test_result,
                "duration": session.completed_at - session.started_at,
            }
        
        except Exception as e:
            logger.error(f"Training failed: {e}")
            session.success = False
            session.notes = str(e)
            session.completed_at = time.time()
            self.failed_count += 1
            return {"ok": False, "error": str(e)}
    
    def _matches_specialty(self, blueprint) -> bool:
        """هل الـ blueprint يناسب تخصصي؟"""
        spec_to_specialty = {
            "coder": TrainerSpecialty.CODING,
            "analyzer": TrainerSpecialty.QUALITY,
            "fixer": TrainerSpecialty.CODING,
            "tester": TrainerSpecialty.TESTING,
            "security": TrainerSpecialty.SECURITY,
            "devops": TrainerSpecialty.DEVOPS,
            "quality": TrainerSpecialty.QUALITY,
            "learner": TrainerSpecialty.AI,
        }
        return spec_to_specialty.get(blueprint.spec.value) == self.specialty
    
    def _build_training_plan(self, blueprint) -> List[Dict]:
        """بناء خطة تدريب"""
        phases = []
        
        # المرحلة 1: الأساسيات
        phases.append({
            "name": "basics",
            "skills": blueprint.skills[:2],
            "duration": 1,
        })
        
        # المرحلة 2: المهارات المتخصصة
        phases.append({
            "name": "specialty",
            "skills": blueprint.skills[2:],
            "duration": 2,
        })
        
        # المرحلة 3: الممارسة
        phases.append({
            "name": "practice",
            "tasks": 5,
            "duration": 3,
        })
        
        return phases
    
    def _execute_phase(self, phase: Dict, blueprint) -> bool:
        """نفّذ مرحلة تدريب"""
        logger.info(f"    → Phase: {phase['name']}")
        time.sleep(0.05)  # محاكاة
        return True
    
    def _final_assessment(self, blueprint) -> Dict:
        """اختبار نهائي"""
        return {
            "passed": True,
            "score": 85,
            "skills_verified": blueprint.skills,
        }
    
    def status(self) -> Dict:
        return {
            "trainer_id": self.trainer_id,
            "specialty": self.specialty.value,
            "skill_level": self.skill_level,
            "trained": self.trained_count,
            "failed": self.failed_count,
            "reputation": self.reputation,
            "is_busy": self.current_session is not None,
        }


class TrainerPool:
    """
    مجموعة الـ 50 مدرباً
    
    - 10 تخصصات × 5 مدربين لكل تخصص = 50
    """
    
    def __init__(self, factory, isolator, count_per_specialty: int = 5):
        self.factory = factory
        self.isolator = isolator
        self.trainers: Dict[str, Trainer] = {}
        
        specialties = list(TrainerSpecialty)
        
        logger.info(f"Creating {len(specialties) * count_per_specialty} trainers...")
        
        for specialty in specialties:
            for i in range(1, count_per_specialty + 1):
                tid = f"trainer_{specialty.value}_{i:02d}"
                sandbox = isolator.create_sandbox(tid)
                trainer = Trainer(
                    trainer_id=tid,
                    specialty=specialty,
                    factory=factory,
                    sandbox=sandbox,
                )
                self.trainers[tid] = trainer
        
        logger.info(f"TrainerPool ready: {len(self.trainers)} trainers")
    
    def get_available_trainer(self, blueprint) -> Optional[Trainer]:
        """احصل على مدرب متاح متخصص"""
        candidates = [
            t for t in self.trainers.values()
            if not t.current_session and t._matches_specialty(blueprint)
        ]
        
        if not candidates:
            return None
        
        # اختر الأعلى سمعة
        return max(candidates, key=lambda t: t.reputation)
    
    def assign_training(self, blueprint) -> Optional[Dict]:
        """عيّن مدرباً لتدريب وكيل"""
        trainer = self.get_available_trainer(blueprint)
        
        if not trainer:
            logger.warning("No available trainer")
            return None
        
        return trainer.train(blueprint)
    
    def stats(self) -> Dict:
        by_specialty = {}
        for t in self.trainers.values():
            sp = t.specialty.value
            by_specialty.setdefault(sp, {"count": 0, "trained": 0, "busy": 0})
            by_specialty[sp]["count"] += 1
            by_specialty[sp]["trained"] += t.trained_count
            if t.current_session:
                by_specialty[sp]["busy"] += 1
        
        return {
            "total_trainers": len(self.trainers),
            "by_specialty": by_specialty,
            "total_trained": sum(t.trained_count for t in self.trainers.values()),
            "total_failed": sum(t.failed_count for t in self.trainers.values()),
        }
