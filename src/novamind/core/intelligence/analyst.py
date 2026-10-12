"""
Analyst — محلل استخبارات
يحلل البيانات ويستخرج أنماطاً وتقارير
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import time
import json
import logging
from collections import Counter

logger = logging.getLogger("intelligence.analyst")


class ThreatLevel(Enum):
    GREEN = ("green", "🟢 آمن")
    YELLOW = ("yellow", "🟡 حذر")
    ORANGE = ("orange", "🟠 خطر")
    RED = ("red", "🔴 خطر شديد")
    BLACK = ("black", "⚫ خطر أمني")
    
    def __init__(self, code: str, arabic: str):
        self.code = code
        self.arabic = arabic


@dataclass
class AnalysisResult:
    """نتيجة تحليل"""
    target_id: str
    analysis_type: str
    threat_level: ThreatLevel
    findings: List[str]
    recommendations: List[str]
    confidence: float  # 0-1
    timestamp: float = 0.0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class Analyst:
    """
    محلل استخبارات
    - يحلل ملاحظات الجواسيس
    - يستخرج أنماطاً
    - يقيّم المخاطر
    - يوصي بإجراءات
    """
    
    def __init__(self, analyst_id: str = "analyst_001"):
        self.analyst_id = analyst_id
        self.analyses: List[AnalysisResult] = []
        
        # عتبات للتحليل
        self.HALLUCINATION_THRESHOLD = 10   # إذا تجاوز = خطر
        self.FAILURE_THRESHOLD = 0.30       # إذا تجاوز = فشل
        self.INACTIVITY_HOURS = 24          # إذا تجاوز = خامل
    
    def analyze_agent(
        self,
        target_id: str,
        observations: List,
        hall_record=None,
        profile=None,
    ) -> AnalysisResult:
        """حلّل وكيلاً واحداً"""
        logger.info(f"Analyzing {target_id}...")
        
        findings = []
        recommendations = []
        threat_score = 0
        confidence = 0.5
        
        # ═══ 1. فحص الهلوسة ═══
        if hall_record:
            hs = hall_record.weighted_score
            if hs >= 30:
                findings.append(f"🚨 هلوسة خطيرة: {hs} نقطة")
                recommendations.append("إحالة فورية للقائد")
                threat_score += 4
                confidence += 0.2
            elif hs >= 15:
                findings.append(f"⚠️ هلوسة مرتفعة: {hs} نقطة")
                recommendations.append("إعادة تدريب إجبارية")
                threat_score += 2
            elif hs >= 5:
                findings.append(f"ملاحظة: {hs} نقطة هلوسة")
                recommendations.append("مراقبة لصيقة")
                threat_score += 1
        
        # ═══ 2. فحص الأداء ═══
        if profile:
            sr = profile.success_rate
            if sr < 0.5:
                findings.append(f"❌ معدل نجاح منخفض: {sr*100:.1f}%")
                recommendations.append("تحقيق في الأسباب")
                threat_score += 3
            elif sr < 0.75:
                findings.append(f"⚠️ معدل نجاح متوسط: {sr*100:.1f}%")
                threat_score += 1
        
        # ═══ 3. فحص الملاحظات ═══
        if observations:
            recent = [o for o in observations if time.time() - o.timestamp < 86400]
            critical = [o for o in recent if o.severity == "critical"]
            alerts = [o for o in recent if o.severity == "alert"]
            
            if critical:
                findings.append(f"🚨 {len(critical)} ملاحظة خطيرة في 24 ساعة")
                recommendations.append("تحقيق عاجل")
                threat_score += 4
            elif alerts:
                findings.append(f"⚠️ {len(alerts)} تنبيه في 24 ساعة")
                threat_score += 2
            
            # أنماط متكررة
            types = Counter(o.observation_type for o in observations)
            most_common = types.most_common(1)
            if most_common and most_common[0][1] >= 3:
                findings.append(f"نمط متكرر: {most_common[0][0]} ({most_common[0][1]} مرة)")
                recommendations.append(f"التحقيق في {most_common[0][0]}")
        
        # ═══ 4. حساب مستوى التهديد ═══
        if threat_score >= 8:
            threat = ThreatLevel.BLACK
        elif threat_score >= 6:
            threat = ThreatLevel.RED
        elif threat_score >= 4:
            threat = ThreatLevel.ORANGE
        elif threat_score >= 2:
            threat = ThreatLevel.YELLOW
        else:
            threat = ThreatLevel.GREEN
        
        # ═══ 5. إذا لم نجد شيئاً ═══
        if not findings:
            findings.append("لا توجد مخالفات ملحوظة")
            recommendations.append("استمرار المراقبة الروتينية")
        
        result = AnalysisResult(
            target_id=target_id,
            analysis_type="agent_assessment",
            threat_level=threat,
            findings=findings,
            recommendations=recommendations,
            confidence=min(1.0, confidence),
        )
        
        self.analyses.append(result)
        return result
    
    def analyze_patterns(self, all_observations: List) -> Dict:
        """حلّل أنماطاً عامة"""
        if not all_observations:
            return {"message": "لا توجد ملاحظات"}
        
        # أنماط حسب الوكيل
        by_target = Counter(o.target_id for o in all_observations)
        
        # أنماط حسب النوع
        by_type = Counter(o.observation_type for o in all_observations)
        
        # أنماط حسب الشدة
        by_severity = Counter(o.severity for o in all_observations)
        
        # أكثر الأوقات نشاطاً
        by_hour = Counter(
            time.strftime("%H", time.localtime(o.timestamp))
            for o in all_observations
        )
        
        return {
            "total_observations": len(all_observations),
            "by_target": dict(by_target.most_common(10)),
            "by_type": dict(by_type.most_common(10)),
            "by_severity": dict(by_severity),
            "by_hour": dict(by_hour.most_common(5)),
            "top_concern": by_target.most_common(1)[0] if by_target else None,
        }
    
    def compare_agents(self, agents_data: List[Dict]) -> Dict:
        """قارن عدة وكلاء"""
        if not agents_data:
            return {}
        
        sorted_by_score = sorted(
            agents_data,
            key=lambda a: a.get("final_score", 0),
            reverse=True,
        )
        
        return {
            "best": sorted_by_score[0] if sorted_by_score else None,
            "worst": sorted_by_score[-1] if sorted_by_score else None,
            "avg_score": sum(a.get("final_score", 0) for a in agents_data) / len(agents_data),
            "total_analyzed": len(agents_data),
        }
