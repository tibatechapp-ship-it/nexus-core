"""Monitoring - يراقب أداء الشركة كاملة."""
import logging
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger("Monitoring")

class Monitor:
    """مراقب: يجمع إحصائيات الشركة ويرسل تنبيهات."""
    
    def __init__(self):
        self.alerts: List[Dict] = []
    
    def alert(self, level: str, message: str, data: Dict = None):
        """يسجّل تنبيهاً."""
        a = {
            "level": level,  # INFO / WARNING / CRITICAL
            "message": message,
            "data": data or {},
            "time": datetime.now().isoformat(),
        }
        self.alerts.append(a)
        logger.log(
            {"INFO": logging.INFO, "WARNING": logging.WARNING, "CRITICAL": logging.CRITICAL}.get(level, logging.INFO),
            f"[{level}] {message}"
        )
        return a
    
    def check_health(self, soldiers: List, brigades: List) -> Dict[str, Any]:
        """فحص صحة الشركة."""
        total = len(soldiers)
        if total == 0:
            return {"status": "EMPTY", "soldiers": 0}
        
        avg_trust = sum(s.stats.trust_score for s in soldiers) / total
        avg_success = sum(s.stats.success_rate for s in soldiers) / total
        hallucinating = sum(1 for s in soldiers if s.stats.hallucination_events > 0)
        
        status = "HEALTHY"
        if avg_trust < 0.4: status = "CRITICAL"
        elif avg_trust < 0.6: status = "WARNING"
        
        if status == "CRITICAL":
            self.alert("CRITICAL", f"Low trust: {avg_trust:.2f}")
        elif status == "WARNING":
            self.alert("WARNING", f"Trust dropping: {avg_trust:.2f}")
        
        return {
            "status": status,
            "soldiers": total,
            "brigades": len(brigades),
            "avg_trust": round(avg_trust, 3),
            "avg_success_rate": round(avg_success, 3),
            "hallucinating": hallucinating,
            "alerts": len(self.alerts),
        }
