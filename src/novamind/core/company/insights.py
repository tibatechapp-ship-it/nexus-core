"""Insights - ملاحظات آلية عن النظام."""
import logging
from typing import List, Dict, Any

logger = logging.getLogger("Insights")


class InsightsEngine:
    """يحلّل النظام ويعطي ملاحظات قابلة للتنفيذ."""
    
    def __init__(self, supreme):
        self.supreme = supreme
    
    def analyze(self) -> List[Dict[str, Any]]:
        """يعيد قائمة ملاحظات."""
        insights = []
        
        # 1. Weak soldiers
        weak = [s for s in self.supreme.soldiers if s.stats.trust_score < 0.4]
        if weak:
            insights.append({
                "level": "WARNING",
                "category": "weak_soldiers",
                "message": f"{len(weak)} جنود ضعفاء (trust < 0.4)",
                "action": "استخدم /purge أو /retrain",
                "data": [{"id": s.id, "trust": round(s.stats.trust_score, 2)} for s in weak[:5]],
            })
        
        # 2. Hallucinations
        hallucinators = [s for s in self.supreme.soldiers if s.stats.hallucination_events >= 3]
        if hallucinators:
            insights.append({
                "level": "CRITICAL",
                "category": "hallucinations",
                "message": f"{len(hallucinators)} جنود يعانون من هلوسات متكررة",
                "action": "استخدم /retrain أو /inject_vaccine",
                "data": [{"id": s.id, "hallucinations": s.stats.hallucination_events} for s in hallucinators],
            })
        
        # 3. Critical genome
        genome_stats = self.supreme.genome.stats()
        if genome_stats.get("total_genes", 0) > 10:
            insights.append({
                "level": "INFO",
                "category": "genome",
                "message": f"{genome_stats['total_genes']} جين مكتشف",
                "action": "راجع الأنماط لتقليل الأخطاء",
            })
        
        # 4. Elite soldiers (for cloning)
        elites = [s for s in self.supreme.soldiers if s.stats.trust_score >= 0.85]
        if elites:
            insights.append({
                "level": "INFO",
                "category": "elite",
                "message": f"{len(elites)} جنود نخبة (trust >= 0.85)",
                "action": "استخدم /clone لتوسيعهم",
                "data": [{"id": s.id, "trust": round(s.stats.trust_score, 2)} for s in elites[:3]],
            })
        
        # 5. Barracks performance
        rankings = self.supreme.barracks.get_rankings()
        if len(rankings) >= 2:
            best = rankings[0]
            worst = rankings[-1]
            if best["score"] > worst["score"] * 1.5:
                insights.append({
                    "level": "INFO",
                    "category": "barracks",
                    "message": f"تفاوت كبير: {best['id']} vs {worst['id']}",
                    "action": "انقل جنوداً من الأفضل إلى الأسوأ",
                })
        
        # 6. Daily targets
        today_stats = self.supreme.targets.stats()
        active = today_stats.get("active_soldiers", 0)
        total = len(self.supreme.soldiers)
        if total > 0 and active < total * 0.5:
            insights.append({
                "level": "WARNING",
                "category": "activity",
                "message": f"{total - active}/{total} من الجنود غير نشطين اليوم",
                "action": "وزّع مهام على الجميع",
            })
        
        return insights
    
    def format_insights(self, insights: List[Dict]) -> str:
        """يحوّل إلى نص Telegram."""
        if not insights:
            return "✅ *لا ملاحظات سلبية*"
        
        msg = "*🔍 ملاحظات النظام:*\n\n"
        for i, ins in enumerate(insights, 1):
            emoji = {
                "CRITICAL": "🚨", "WARNING": "⚠️",
                "INFO": "ℹ️", "SUCCESS": "✅"
            }.get(ins["level"], "•")
            
            msg += f"{emoji} *{ins['category']}*\n"
            msg += f"  {ins['message']}\n"
            msg += f"  _الإجراء:_ {ins['action']}\n"
            
            if ins.get("data"):
                for d in ins["data"][:3]:
                    if isinstance(d, dict):
                        msg += f"    - {d}\n"
            msg += "\n"
        
        return msg
