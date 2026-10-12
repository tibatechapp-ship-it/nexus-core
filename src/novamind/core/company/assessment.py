"""Assessment Center - يقيّم ويقرر الترقية/التخفيض."""
import logging
from typing import Dict, Any, List
from datetime import datetime

from novamind.core.company.soldier import Soldier
from novamind.core.company.ranks import Rank
from novamind.core.company.audit import AuditTrail

logger = logging.getLogger("Assessment")

class AssessmentCenter:
    """مركز التقييم: يراقب الأداء ويقرر الترقيات."""
    
    def __init__(self, audit: AuditTrail = None):
        self.audit = audit
        self.log: List[Dict] = []
    
    def evaluate(self, soldier: Soldier) -> Dict[str, Any]:
        """يقيّم جندياً ويعيد توصية."""
        stats = soldier.stats
        recommendation = "KEEP"
        reason = ""
        
        # ترقية
        if soldier.check_promotion():
            if soldier.stats.trust_score >= 0.7:
                recommendation = "PROMOTE"
                reason = f"Trust {soldier.stats.trust_score:.2f} + {stats.tasks_completed} tasks"
        
        # تخفيض
        elif stats.hallucination_events >= 3:
            recommendation = "DEMOTE"
            reason = f"Too many hallucinations: {stats.hallucination_events}"
        
        elif stats.tasks_failed >= 5 and stats.success_rate < 0.4:
            recommendation = "DEMOTE"
            reason = f"Low success rate: {stats.success_rate:.2f}"
        
        # إعادة تدريب
        elif stats.success_rate < 0.6 and stats.tasks_completed > 0:
            recommendation = "RETRAIN"
            reason = f"Success rate {stats.success_rate:.2f} needs improvement"
        
        # تطبيق
        if recommendation == "PROMOTE":
            soldier.promote()
        elif recommendation == "DEMOTE":
            soldier.demote()
        
        result = {
            "soldier_id": soldier.id,
            "recommendation": recommendation,
            "reason": reason,
            "rank_before": soldier.rank.name,
            "trust": round(stats.trust_score, 3),
            "success_rate": round(stats.success_rate, 3),
            "tasks": stats.tasks_completed,
            "hallucinations": stats.hallucination_events,
            "time": datetime.now().isoformat(),
        }
        self.log.append(result)
        
        # سجل في HMAC audit
        if self.audit:
            self.audit.record("assessment", soldier.id, result)
        
        logger.info(f"Assessed {soldier.id}: {recommendation} — {reason}")
        return result
    
    def evaluate_brigade(self, soldiers: List[Soldier]) -> Dict[str, Any]:
        """يقيّم كتيبة كاملة."""
        results = [self.evaluate(s) for s in soldiers]
        promotions = sum(1 for r in results if r["recommendation"] == "PROMOTE")
        demotions = sum(1 for r in results if r["recommendation"] == "DEMOTE")
        retrains = sum(1 for r in results if r["recommendation"] == "RETRAIN")
        return {
            "total": len(soldiers),
            "promoted": promotions,
            "demoted": demotions,
            "retrained": retrains,
            "kept": len(soldiers) - promotions - demotions - retrains,
            "details": results,
        }
