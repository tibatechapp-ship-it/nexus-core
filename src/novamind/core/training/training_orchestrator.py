"""
TrainingOrchestrator — المنسّق الرئيسي للتدريب
يربط كل مكونات التدريب معاً
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time
import logging

from .training_plans import (
    TrainingPlan, TrainingModule, TrainingPhase,
    get_training_plan,
)
from .training_executor import TrainingExecutor, TraineeProgress
from .training_simulator import TrainingSimulator, TaskDifficulty

logger = logging.getLogger("training.orchestrator")


@dataclass
class TrainingSession:
    """جلسة تدريب كاملة"""
    session_id: str
    agent_id: str
    spec: str
    started_at: float
    completed_at: float = 0.0
    final_score: float = 0.0
    graduated: bool = False
    phases: List[Dict] = field(default_factory=list)
    simulation: Optional[Dict] = None


class TrainingOrchestrator:
    """
    المنسّق الرئيسي
    يدير كل عمليات التدريب
    """

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.executor = TrainingExecutor()
        self.simulator = TrainingSimulator()
        self.sessions: List[TrainingSession] = []
        self.session_counter = 0

        logger.info("TrainingOrchestrator ready")

    def _new_session_id(self) -> str:
        self.session_counter += 1
        return f"TRN-{int(time.time())}-{self.session_counter:04d}"

    def train_agent(
        self,
        agent_id: str,
        spec: str,
        trainer_quality: float = 0.85,
        include_simulation: bool = True,
    ) -> TrainingSession:
        """
        درّب وكيلاً كاملاً
        """
        session = TrainingSession(
            session_id=self._new_session_id(),
            agent_id=agent_id,
            spec=spec,
            started_at=time.time(),
        )

        logger.info(f"🎓 Starting training session: {session.session_id}")

        # ─── 1. التدريب النظري (Phases 1-5) ───
        training_result = self.executor.run_full_training(
            agent_id=agent_id,
            spec=spec,
            trainer_quality=trainer_quality,
        )
        session.phases = training_result.get("phases", [])

        # ─── 2. المحاكاة (Phase 6) ───
        if include_simulation:
            sim_result = self.simulator.run_suite(agent_id, spec)
            session.simulation = sim_result

        # ─── 3. القرار النهائي ───
        session.completed_at = time.time()

        # احسب الدرجة النهائية
        theory_score = training_result.get("average_score", 0)
        sim_score = (session.simulation or {}).get("avg_score", 0) if include_simulation else theory_score

        if include_simulation:
            session.final_score = round((theory_score * 0.6 + sim_score * 0.4), 3)
        else:
            session.final_score = theory_score

        session.graduated = (
            training_result.get("is_graduated", False) and
            (sim_score >= 0.7 if include_simulation else True) and
            session.final_score >= 0.75
        )

        self.sessions.append(session)

        if session.graduated:
            logger.info(
                f"🎉 {agent_id} GRADUATED — "
                f"final={session.final_score:.2f} "
                f"(theory={theory_score:.2f}, sim={sim_score:.2f})"
            )
        else:
            logger.warning(f"⚠️ {agent_id} did NOT graduate — score={session.final_score}")

        return session

    def retrain_weak_agent(
        self,
        agent_id: str,
        spec: str,
        weak_areas: Optional[List[str]] = None,
    ) -> TrainingSession:
        """أعد تدريب وكيل ضعيف"""
        logger.info(f"🔁 Retraining {agent_id} ({spec})")

        # درّب بجودة أقل ليركّز على الضعف
        return self.train_agent(
            agent_id=agent_id,
            spec=spec,
            trainer_quality=0.75,  # جودة أقل
            include_simulation=True,
        )

    def batch_train(
        self,
        agents: List[Dict],  # [{"agent_id": ..., "spec": ...}, ...]
        trainer_quality: float = 0.85,
    ) -> List[TrainingSession]:
        """درّب مجموعة وكلاء"""
        results = []
        for agent in agents:
            session = self.train_agent(
                agent["agent_id"],
                agent["spec"],
                trainer_quality,
            )
            results.append(session)
        return results

    def get_plan_summary(self, spec: str) -> Dict:
        """ملخص خطة تدريب"""
        plan = get_training_plan(spec)
        by_phase: Dict[str, int] = {}
        for m in plan.modules:
            by_phase[m.phase.value] = by_phase.get(m.phase.value, 0) + 1

        return {
            "spec": spec,
            "total_hours": plan.total_hours,
            "total_modules": len(plan.modules),
            "by_phase": by_phase,
            "graduation_score": plan.graduation_min_score,
        }

    def stats(self) -> Dict:
        graduated = sum(1 for s in self.sessions if s.graduated)
        return {
            "total_sessions": len(self.sessions),
            "graduated": graduated,
            "failed": len(self.sessions) - graduated,
            "graduation_rate": round(
                graduated / max(1, len(self.sessions)), 3
            ),
            "executor": self.executor.stats(),
            "simulator": self.simulator.stats(),
        }
