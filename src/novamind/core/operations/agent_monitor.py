"""AgentMonitor — مراقبة أداء الوكلاء العاملين"""
from dataclasses import dataclass
from typing import Dict, List
from enum import Enum
import time
import logging

logger = logging.getLogger("agent_monitor")


class HealthStatus(Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AgentMetrics:
    agent_id: str
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_response_time: float = 0.0
    last_task_at: float = 0.0
    error_count: int = 0
    
    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 1.0
    
    @property
    def health(self) -> HealthStatus:
        sr = self.success_rate
        if sr >= 0.9: return HealthStatus.EXCELLENT
        if sr >= 0.75: return HealthStatus.GOOD
        if sr >= 0.6: return HealthStatus.WARNING
        return HealthStatus.CRITICAL


class AgentMonitor:
    """مراقب مستمر لأداء الوكلاء"""
    
    def __init__(self):
        self.metrics: Dict[str, AgentMetrics] = {}
        self.alerts: List[Dict] = []
    
    def register(self, agent_id: str):
        self.metrics[agent_id] = AgentMetrics(agent_id=agent_id)
    
    def record_task(self, agent_id: str, success: bool, duration: float):
        if agent_id not in self.metrics:
            self.register(agent_id)
        
        m = self.metrics[agent_id]
        if success:
            m.tasks_completed += 1
        else:
            m.tasks_failed += 1
            m.error_count += 1
        
        n = m.tasks_completed + m.tasks_failed
        m.avg_response_time = (m.avg_response_time * (n - 1) + duration) / n
        m.last_task_at = time.time()
        
        if m.health == HealthStatus.CRITICAL:
            self._alert_critical(agent_id, m)
    
    def _alert_critical(self, agent_id: str, metrics: AgentMetrics):
        alert = {
            "level": "CRITICAL",
            "agent_id": agent_id,
            "success_rate": metrics.success_rate,
            "at": time.time(),
            "action": "needs_retraining",
        }
        self.alerts.append(alert)
        logger.warning(f"⚠️ CRITICAL: {agent_id} needs retraining (SR={metrics.success_rate:.2f})")
    
    def health_report(self) -> Dict:
        by_status = {s.value: 0 for s in HealthStatus}
        for m in self.metrics.values():
            by_status[m.health.value] += 1
        
        return {
            "total_agents": len(self.metrics),
            "by_status": by_status,
            "critical_alerts": len(self.alerts),
            "needs_retraining": [
                aid for aid, m in self.metrics.items()
                if m.health == HealthStatus.CRITICAL
            ],
        }
