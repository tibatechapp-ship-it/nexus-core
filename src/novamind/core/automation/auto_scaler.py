"""
AutoScaler — التوسيع التلقائي
يزيد أو يقلل الوكلاء حسب الحمل
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import time
import logging

logger = logging.getLogger("auto_scaler")


class ScalingAction(Enum):
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    MAINTAIN = "maintain"


@dataclass
class ScalingPolicy:
    """سياسة التوسيع"""
    # عتبات التوسيع
    queue_high: int = 10        # إذا الطابور > 10 → وسّع
    queue_low: int = 2          # إذا الطابور < 2 → قلّص
    response_time_high: float = 30.0  # ثواني
    response_time_low: float = 5.0
    utilization_high: float = 0.85
    utilization_low: float = 0.30
    max_agents: int = 200
    min_agents: int = 5
    cooldown_seconds: int = 300  # 5 دقائق بين التوسيعات


class AutoScaler:
    """
    مُوسِّع تلقائي
    - يراقب الحمل
    - يوسّع أو يقلّص
    """
    
    def __init__(self, policy: Optional[ScalingPolicy] = None):
        self.policy = policy or ScalingPolicy()
        self.last_scaling_time = 0
        self.scaling_history: List[Dict] = []
        self.current_agents = 0
        self.target_agents = 5
    
    def evaluate(self, metrics: Dict) -> Dict:
        """قيّم الوضع"""
        queue_len = metrics.get("queue_length", 0)
        avg_response = metrics.get("avg_response_time", 10)
        utilization = metrics.get("utilization", 0.5)
        active_agents = metrics.get("active_agents", 0)
        
        self.current_agents = active_agents
        
        # cooldown
        if time.time() - self.last_scaling_time < self.policy.cooldown_seconds:
            return {
                "action": ScalingAction.MAINTAIN.value,
                "reason": "cooldown",
                "current": active_agents,
            }
        
        # ═══ قرار التوسيع ═══
        action = ScalingAction.MAINTAIN
        reason = ""
        delta = 0
        
        # scale up
        if (queue_len > self.policy.queue_high or
            avg_response > self.policy.response_time_high or
            utilization > self.policy.utilization_high):
            
            if active_agents < self.policy.max_agents:
                action = ScalingAction.SCALE_UP
                delta = min(5, self.policy.max_agents - active_agents)
                reason = f"high_load (queue={queue_len}, resp={avg_response:.1f}s, util={utilization:.0%})"
        
        # scale down
        elif (queue_len < self.policy.queue_low and
              avg_response < self.policy.response_time_low and
              utilization < self.policy.utilization_low):
            
            if active_agents > self.policy.min_agents:
                action = ScalingAction.SCALE_DOWN
                delta = -min(2, active_agents - self.policy.min_agents)
                reason = f"low_load"
        
        # نفّذ
        if action != ScalingAction.MAINTAIN:
            self.target_agents = active_agents + delta
            self.last_scaling_time = time.time()
            self.scaling_history.append({
                "at": time.time(),
                "action": action.value,
                "from": active_agents,
                "to": self.target_agents,
                "reason": reason,
            })
            logger.info(f"⚖️ {action.value}: {active_agents} → {self.target_agents} ({reason})")
        
        return {
            "action": action.value,
            "reason": reason,
            "current": active_agents,
            "target": self.target_agents,
            "delta": delta,
        }
    
    def stats(self) -> Dict:
        return {
            "current_agents": self.current_agents,
            "target_agents": self.target_agents,
            "policy": {
                "queue_high": self.policy.queue_high,
                "queue_low": self.policy.queue_low,
                "max": self.policy.max_agents,
                "min": self.policy.min_agents,
            },
            "scalings_performed": len(self.scaling_history),
            "last_scalings": self.scaling_history[-5:],
        }
