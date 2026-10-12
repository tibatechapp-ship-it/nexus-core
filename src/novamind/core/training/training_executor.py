"""
TrainingExecutor — ينفّذ خطة التدريب
يدير كل جلسة تدريب
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time
import logging

from .training_plans import (
    TrainingPlan, TrainingModule, TrainingPhase,
    get_training_plan,
)

logger = logging.getLogger("training.executor")


@dataclass
class ModuleResult:
    """نتيجة وحدة تدريب"""
    module_name: str
    phase: str
    score: float
    passed: bool
    duration: float
    notes: str = ""


@dataclass
class TraineeProgress:
    """تقدم متدرب"""
    agent_id: str
    spec: str
    current_phase: TrainingPhase
    completed_modules: List[ModuleResult] = field(default_factory=list)
    failed_modules: List[ModuleResult] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0
    total_hours: float = 0.0

    @property
    def completion_rate(self) -> float:
        plan = get_training_plan(self.spec)
        total = len(plan.modules)
        done = len(self.completed_modules)
        return done / total if total else 0.0

    @property
    def average_score(self) -> float:
        if not self.completed_modules:
            return 0.0
        return sum(m.score for m in self.completed_modules) / len(self.completed_modules)

    @property
    def is_graduated(self) -> bool:
        # معايير التخرج:
        # 1. اكتمل 80% من الوحدات على الأقل
        # 2. متوسط الدرجات 0.75+
        # 3. لا توجد وحدة فاشلة حرجة (score < 0.5)
        if self.completion_rate < 0.8:
            return False
        if self.average_score < 0.75:
            return False
        critical_failures = [m for m in self.failed_modules if m.score < 0.5]
        if critical_failures:
            return False
        return True


class TrainingExecutor:
    """
    منفّذ التدريب
    يدير كل جلسات التدريب
    """

    def __init__(self):
        self.trainees: Dict[str, TraineeProgress] = {}
        self.sessions_completed = 0
        self.modules_executed = 0

    def enroll(self, agent_id: str, spec: str) -> TraineeProgress:
        """سجّل متدرباً"""
        progress = TraineeProgress(
            agent_id=agent_id,
            spec=spec,
            current_phase=TrainingPhase.FOUNDATION,
            started_at=time.time(),
        )
        self.trainees[agent_id] = progress
        logger.info(f"📚 Enrolled {agent_id} in {spec} training")
        return progress

    def execute_module(
        self,
        agent_id: str,
        module: TrainingModule,
        trainer_quality: float = 0.85,
    ) -> ModuleResult:
        """نفّذ وحدة تدريب"""
        start = time.time()

        # احسب النتيجة بناءً على جودة المدرب
        import random
        score = max(0.0, min(1.0, trainer_quality + random.gauss(0, 0.08)))
        passed = score >= module.min_score

        result = ModuleResult(
            module_name=module.name,
            phase=module.phase.value,
            score=round(score, 3),
            passed=passed,
            duration=time.time() - start,
        )

        self.modules_executed += 1
        logger.info(
            f"  {'✅' if passed else '❌'} {agent_id} — {module.name} "
            f"({score:.2f})"
        )

        return result

    def run_phase(
        self,
        agent_id: str,
        phase: TrainingPhase,
        trainer_quality: float = 0.85,
    ) -> Dict:
        """نفّذ مرحلة كاملة"""
        progress = self.trainees.get(agent_id)
        if not progress:
            return {"error": "not_enrolled"}

        plan = get_training_plan(progress.spec)
        phase_modules = [m for m in plan.modules if m.phase == phase]

        logger.info(f"📍 Phase: {phase.value} ({len(phase_modules)} modules)")

        results = []
        for module in phase_modules:
            result = self.execute_module(agent_id, module, trainer_quality)
            if result.passed:
                progress.completed_modules.append(result)
            else:
                progress.failed_modules.append(result)
            results.append(result)

        passed = sum(1 for r in results if r.passed)
        return {
            "phase": phase.value,
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "success_rate": round(passed / max(1, len(results)), 3),
        }

    def run_full_training(
        self,
        agent_id: str,
        spec: str,
        trainer_quality: float = 0.85,
    ) -> Dict:
        """نفّذ التدريب الكامل"""
        logger.info(f"🎓 Starting full training for {agent_id} ({spec})")

        self.enroll(agent_id, spec)

        phases_in_order = [
            TrainingPhase.FOUNDATION,
            TrainingPhase.SPECIALIZATION,
            TrainingPhase.SIMULATION,
            TrainingPhase.EVALUATION,
            TrainingPhase.TEAMWORK,
        ]

        phase_results = []
        for phase in phases_in_order:
            result = self.run_phase(agent_id, phase, trainer_quality)
            phase_results.append(result)

            # إذا فشل الطالب بشكل كبير، أوقف
            if result.get("success_rate", 0) < 0.5:
                logger.warning(f"⚠️ {agent_id} failed at {phase.value}")
                break

        progress = self.trainees[agent_id]
        progress.completed_at = time.time()

        summary = {
            "agent_id": agent_id,
            "spec": spec,
            "completion_rate": round(progress.completion_rate, 3),
            "average_score": round(progress.average_score, 3),
            "is_graduated": progress.is_graduated,
            "phases": phase_results,
            "duration": progress.completed_at - progress.started_at,
        }

        if progress.is_graduated:
            logger.info(f"🎉 {agent_id} GRADUATED with score {progress.average_score:.2f}")
            self.sessions_completed += 1
        else:
            logger.warning(f"⚠️ {agent_id} did NOT graduate")

        return summary

    def get_progress(self, agent_id: str) -> Optional[Dict]:
        """احصل على تقدم متدرب"""
        progress = self.trainees.get(agent_id)
        if not progress:
            return None
        return {
            "agent_id": progress.agent_id,
            "spec": progress.spec,
            "current_phase": progress.current_phase.value,
            "completed": len(progress.completed_modules),
            "failed": len(progress.failed_modules),
            "completion_rate": round(progress.completion_rate, 3),
            "average_score": round(progress.average_score, 3),
            "is_graduated": progress.is_graduated,
        }

    def stats(self) -> Dict:
        return {
            "total_trainees": len(self.trainees),
            "sessions_completed": self.sessions_completed,
            "modules_executed": self.modules_executed,
            "graduated": sum(1 for t in self.trainees.values() if t.is_graduated),
        }
