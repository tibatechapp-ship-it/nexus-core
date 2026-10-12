"""
TrainingSimulator — يحاكي مهام حقيقية
يستخدم للتدريب الميداني (Phase 6)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from enum import Enum
import time
import logging

logger = logging.getLogger("training.simulator")


class TaskDifficulty(Enum):
    EASY = 1
    MEDIUM = 2
    HARD = 3
    EXPERT = 4
    MASTER = 5


@dataclass
class SimulatedTask:
    task_id: str
    spec: str
    difficulty: TaskDifficulty
    prompt: str
    expected_output: str
    validation: str
    max_time: int = 300


@dataclass
class TaskResult:
    task_id: str
    success: bool
    score: float
    duration: float
    output: str = ""
    error: str = ""


TASK_LIBRARY = {
    "coder": [
        SimulatedTask("c1", "coder", TaskDifficulty.EASY,
            "اكتب دالة add(a,b) في Python",
            "def add(a, b): return a + b",
            "تشغيل الدالة والتحقق من add(2,3)==5"),
        SimulatedTask("c2", "coder", TaskDifficulty.MEDIUM,
            "اكتب class Stack مع push/pop/peek",
            "class Stack: ...", "اختبار العمليات الأساسية"),
        SimulatedTask("c3", "coder", TaskDifficulty.HARD,
            "اكتب دالة تكتشف الأقواس المتوازنة",
            "def is_balanced(s): ...", "اختبار حالات متعددة"),
        SimulatedTask("c4", "coder", TaskDifficulty.EXPERT,
            "اكتب LRU Cache بـ O(1)",
            "class LRUCache: ...", "اختبار الأداء والسلوك"),
    ],
    "security": [
        SimulatedTask("s1", "security", TaskDifficulty.EASY,
            "اكتشف SQL Injection في كود",
            "تقرير مفصل", "التحقق من ذكر SQL Injection"),
        SimulatedTask("s2", "security", TaskDifficulty.MEDIUM,
            "اكتشف جميع الثغرات في كود",
            "قائمة بالثغرات", "تغطية 3+ ثغرات"),
        SimulatedTask("s3", "security", TaskDifficulty.HARD,
            "اقترح إصلاحاً آمناً لثغرة XSS",
            "كود مُصلح", "اختبار الإصلاح"),
    ],
    "devops": [
        SimulatedTask("d1", "devops", TaskDifficulty.EASY,
            "اكتب Dockerfile لتطبيق Python",
            "Dockerfile صالح", "بناء الصورة"),
        SimulatedTask("d2", "devops", TaskDifficulty.MEDIUM,
            "اكتب docker-compose لـ web + db",
            "docker-compose.yml", "تشغيل المكدس"),
    ],
    "quality": [
        SimulatedTask("q1", "quality", TaskDifficulty.EASY,
            "اكتب تقرير مراجعة لكود",
            "تقرير منظم", "التحقق من التغطية"),
        SimulatedTask("q2", "quality", TaskDifficulty.MEDIUM,
            "اقترح 5 تحسينات لكود",
            "قائمة تحسينات", "5 اقتراحات محددة"),
    ],
}


class TrainingSimulator:
    """محاكي التدريب"""

    def __init__(self, secure_channel=None):
        self.secure_channel = secure_channel
        self.tasks: Dict[str, SimulatedTask] = {}
        for tasks in TASK_LIBRARY.values():
            for t in tasks:
                self.tasks[t.task_id] = t
        self.executed: List[TaskResult] = []

    def get_tasks_for(self, spec: str, max_difficulty=None) -> List[SimulatedTask]:
        if max_difficulty is None:
            max_difficulty = TaskDifficulty.MASTER
        return [
            t for t in self.tasks.values()
            if t.spec == spec and t.difficulty.value <= max_difficulty.value
        ]

    def execute_task(self, agent_id: str, task: SimulatedTask,
                     agent_fn: Optional[Callable] = None) -> TaskResult:
        start = time.time()
        try:
            if agent_fn:
                output = agent_fn(task.prompt)
                success = len(output) > 50
                score = min(1.0, len(output) / 500) if success else 0.0
            else:
                import random
                score = random.uniform(0.6, 1.0)
                success = score >= 0.7
                output = "(simulated)"

            result = TaskResult(
                task_id=task.task_id, success=success,
                score=round(score, 3),
                duration=time.time() - start,
                output=output[:200],
            )
        except Exception as e:
            result = TaskResult(
                task_id=task.task_id, success=False, score=0.0,
                duration=time.time() - start, error=str(e),
            )
        self.executed.append(result)
        return result

    def run_suite(self, agent_id: str, spec: str,
                  agent_fn: Optional[Callable] = None) -> Dict:
        tasks = self.get_tasks_for(spec)
        results = []
        for task in tasks:
            r = self.execute_task(agent_id, task, agent_fn)
            results.append(r)

        passed = sum(1 for r in results if r.success)
        avg_score = sum(r.score for r in results) / len(results) if results else 0.0

        return {
            "agent_id": agent_id, "spec": spec,
            "total_tasks": len(tasks), "passed": passed,
            "failed": len(results) - passed,
            "success_rate": round(passed / max(1, len(tasks)), 3),
            "avg_score": round(avg_score, 3),
            "results": [r.__dict__ for r in results],
        }

    def stats(self) -> Dict:
        return {
            "total_tasks_library": len(self.tasks),
            "executed_tasks": len(self.executed),
            "successful": sum(1 for r in self.executed if r.success),
        }
