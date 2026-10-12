"""نظام التدريب والتصنيع"""
from .training_plans import (
    TrainingPlan, TrainingModule, TrainingPhase,
    get_training_plan,
)
from .training_executor import (
    TrainingExecutor, TraineeProgress, ModuleResult,
)
from .training_simulator import (
    TrainingSimulator, SimulatedTask, TaskResult, TaskDifficulty,
)
from .training_orchestrator import (
    TrainingOrchestrator, TrainingSession,
)
__all__ = [
    "TrainingPlan", "TrainingModule", "TrainingPhase", "get_training_plan",
    "TrainingExecutor", "TraineeProgress", "ModuleResult",
    "TrainingSimulator", "SimulatedTask", "TaskResult", "TaskDifficulty",
    "TrainingOrchestrator", "TrainingSession",
]
