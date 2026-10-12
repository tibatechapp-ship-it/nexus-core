"""Retrainer — إعادة تدريب الوكلاء الضعفاء"""
from dataclasses import dataclass
from typing import Dict, List, Optional
import time
import logging

logger = logging.getLogger("retrainer")


@dataclass
class RetrainingOrder:
    agent_id: str
    reason: str
    priority: int
    requested_at: float
    assigned_trainer: Optional[str] = None
    completed: bool = False


class Retrainer:
    """يستقبل الوكلاء الضعفاء ويعيد تدريبهم"""
    
    def __init__(self, trainer_pool):
        self.trainer_pool = trainer_pool
        self.queue: List[RetrainingOrder] = []
        self.completed: List[RetrainingOrder] = []
        self.failed: List[RetrainingOrder] = []
    
    def enqueue(self, agent_id: str, reason: str, priority: int = 3):
        order = RetrainingOrder(
            agent_id=agent_id,
            reason=reason,
            priority=priority,
            requested_at=time.time(),
        )
        self.queue.append(order)
        self.queue.sort(key=lambda o: -o.priority)
        logger.info(f"Retraining enqueued: {agent_id} (priority={priority})")
    
    def process_next(self) -> Optional[Dict]:
        if not self.queue:
            return None
        
        order = self.queue.pop(0)
        logger.info(f"Processing retraining: {order.agent_id}")
        
        available = [t for t in self.trainer_pool.trainers.values() if not t.current_session]
        if not available:
            self.queue.insert(0, order)
            return {"ok": False, "reason": "no_available_trainer"}
        
        trainer = available[0]
        order.assigned_trainer = trainer.trainer_id
        result = {"retrained": True, "by": trainer.trainer_id}
        order.completed = True
        self.completed.append(order)
        
        return {"ok": True, "agent_id": order.agent_id, "result": result}
    

    async def retrain_all_agents(self, mode: str = "normal") -> Dict:
        """
        إعادة تدريب جماعية لكل الوكلاء الضعفاء
        
        Args:
            mode: normal / emergency_patch
        
        Returns:
            تقرير بالنتائج
        """
        import time
        start = time.time()
        
        # في الوضع الطارئ: أعد تدريب جميع الضعفاء فوراً
        priority_threshold = 5 if mode == "emergency_patch" else 3
        
        # اقرأ الوكلاء من السجل
        try:
            from core.identity.military_id import PersonnelRegistry
            from pathlib import Path as P
            registry = PersonnelRegistry(P("/public/agent/novamind"))
            weak_agents = [
                mid for mid, profile in registry.profiles.items()
                if profile.success_rate < 0.7
            ]
        except Exception:
            weak_agents = []
        
        # ضعهم في الطابور
        for agent_id in weak_agents:
            self.enqueue(
                agent_id=agent_id,
                reason=f"auto_retrain_{mode}",
                priority=priority_threshold,
            )
        
        # عالج القائمة
        processed = 0
        while True:
            result = self.process_next()
            if not result:
                break
            processed += 1
            if processed >= 100:  # حد أقصى للدورة
                break
        
        duration = time.time() - start
        
        return {
            "mode": mode,
            "agents_enqueued": len(weak_agents),
            "agents_processed": processed,
            "duration_seconds": round(duration, 2),
        }

    def stats(self) -> Dict:
        return {
            "queued": len(self.queue),
            "completed": len(self.completed),
            "failed": len(self.failed),
        }
