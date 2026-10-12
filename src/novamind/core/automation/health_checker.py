"""
HealthChecker — فاحص صحة النظام
يفحص كل المكونات بشكل دوري
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import time
import threading
import logging

logger = logging.getLogger("health_checker")


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    last_check: float
    message: str = ""
    metrics: Dict = field(default_factory=dict)


class HealthChecker:
    """فاحص صحة كل المكونات"""
    
    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self.components: Dict[str, Any] = {}
        self.health_history: List[Dict] = []
        self.state = "stopped"
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def register(self, name: str, instance: Any, check_fn=None):
        """سجّل مكوناً"""
        self.components[name] = {
            "instance": instance,
            "check_fn": check_fn,
        }
        logger.info(f"Registered component: {name}")
    
    def start(self):
        """ابدأ الفحص"""
        if self.state == "running":
            return
        self.state = "running"
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("❤️ HealthChecker started")
    
    def stop(self):
        """أوقف"""
        self._stop_event.set()
        self.state = "stopped"
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("HealthChecker stopped")
    
    def _run(self):
        """الحلقة"""
        while not self._stop_event.is_set():
            try:
                self._check_all()
                if self._stop_event.wait(timeout=self.check_interval):
                    break
            except Exception as e:
                logger.error(f"Health check error: {e}")
                time.sleep(5)
    
    def _check_all(self):
        """افحص الكل"""
        report = {
            "timestamp": time.time(),
            "components": {},
            "overall": "healthy",
        }
        
        worst = HealthStatus.HEALTHY
        
        for name, comp in self.components.items():
            health = self._check_one(name, comp)
            report["components"][name] = {
                "status": health.status.value,
                "message": health.message,
                "metrics": health.metrics,
            }
            
            # حدد الأسوأ
            if health.status == HealthStatus.CRITICAL:
                worst = HealthStatus.CRITICAL
            elif health.status == HealthStatus.UNHEALTHY and worst != HealthStatus.CRITICAL:
                worst = HealthStatus.UNHEALTHY
            elif health.status == HealthStatus.DEGRADED and worst == HealthStatus.HEALTHY:
                worst = HealthStatus.DEGRADED
        
        report["overall"] = worst.value
        self.health_history.append(report)
        
        # احتفظ بآخر 100
        if len(self.health_history) > 100:
            self.health_history = self.health_history[-100:]
    
    def _check_one(self, name: str, comp: Dict) -> ComponentHealth:
        """افحص مكوناً واحداً"""
        try:
            instance = comp["instance"]
            check_fn = comp["check_fn"]
            
            if check_fn:
                result = check_fn(instance)
                return ComponentHealth(
                    name=name,
                    status=result.get("status", HealthStatus.HEALTHY),
                    last_check=time.time(),
                    message=result.get("message", ""),
                    metrics=result.get("metrics", {}),
                )
            
            # فحص عام — هل المكون يعمل؟
            if hasattr(instance, "state"):
                state = getattr(instance, "state")
                state_val = state.value if hasattr(state, "value") else str(state)
                if state_val == "running":
                    return ComponentHealth(name, HealthStatus.HEALTHY, time.time())
                else:
                    return ComponentHealth(name, HealthStatus.DEGRADED, time.time(), f"state={state_val}")
            
            return ComponentHealth(name, HealthStatus.HEALTHY, time.time())
        
        except Exception as e:
            return ComponentHealth(name, HealthStatus.CRITICAL, time.time(), str(e))
    
    def stats(self) -> Dict:
        """إحصائيات"""
        if not self.health_history:
            return {"state": self.state, "checks": 0}
        
        latest = self.health_history[-1]
        return {
            "state": self.state,
            "checks_performed": len(self.health_history),
            "overall_health": latest["overall"],
            "components": latest["components"],
        }
