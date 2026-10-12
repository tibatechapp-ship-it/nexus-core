"""
IntelligenceAgency — وكالة الاستخبارات
- تدير كل الجواسيس
- تجمع المعلومات
- تحلل
- تُصدر تقارير سرية للقائد
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import time
import json
import logging

from .spy import SpyNetwork, Spy, SpyType, Observation
from .analyst import Analyst, AnalysisResult, ThreatLevel

logger = logging.getLogger("intelligence.agency")


class ReportType(Enum):
    """أنواع التقارير"""
    DAILY = "daily"                 # تقرير يومي
    WEEKLY = "weekly"               # تقرير أسبوعي
    INCIDENT = "incident"           # تقرير حادثة
    THREAT = "threat"               # تقرير تهديد
    PERFORMANCE = "performance"     # تقرير أداء
    RECOMMENDATION = "recommendation"  # توصية


class ReportClassification(Enum):
    """تصنيف التقارير"""
    INTERNAL = "internal"           # للاستخدام الداخلي
    CONFIDENTIAL = "confidential"   # سري
    SECRET = "secret"               # سري جداً
    TOP_SECRET = "top_secret"       # سري للغاية — للقائد فقط


@dataclass
class Report:
    """تقرير استخباراتي"""
    report_id: str
    report_type: ReportType
    classification: ReportClassification
    title: str
    summary: str
    findings: List[Dict]
    recommendations: List[str]
    threat_level: ThreatLevel
    target_ids: List[str]
    generated_at: float = 0.0
    expires_at: float = 0.0
    
    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = time.time()
        if not self.expires_at:
            self.expires_at = self.generated_at + 86400  # 24 ساعة افتراضياً
    
    def to_dict(self) -> Dict:
        return {
            "report_id": self.report_id,
            "type": self.report_type.value,
            "classification": self.classification.value,
            "title": self.title,
            "summary": self.summary,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "threat_level": self.threat_level.code,
            "threat_arabic": self.threat_level.arabic,
            "target_ids": self.target_ids,
            "generated_at": self.generated_at,
            "expires_at": self.expires_at,
        }
    
    def to_arabic_report(self) -> str:
        """تقرير عربي كامل"""
        lines = [
            "╔" + "═" * 68 + "╗",
            f"║  🕵️  تقرير استخباراتي — {self.report_type.value.upper():<38} ║",
            "╠" + "═" * 68 + "╣",
            f"║ رقم التقرير: {self.report_id:<50} ║",
            f"║ التصنيف: {self.classification.value:<53} ║",
            f"║ مستوى التهديد: {self.threat_level.arabic:<46} ║",
            f"║ الوقت: {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.generated_at)):<53} ║",
            "╠" + "═" * 68 + "╣",
            f"║ 📋 العنوان: {self.title[:55]:<55} ║",
            "╠" + "═" * 68 + "╣",
            "║ 📝 الملخص:                                                    ║",
        ]
        
        # أضف الملخص
        for line in self.summary.split("\n")[:5]:
            lines.append(f"║  {line[:64]:<64}  ║")
        
        lines.append("╠" + "═" * 68 + "╣")
        lines.append("║ 🔍 النتائج:                                                  ║")
        
        for i, finding in enumerate(self.findings[:10], 1):
            desc = finding.get("description", str(finding))[:60]
            lines.append(f"║  {i}. {desc:<62}  ║")
        
        lines.append("╠" + "═" * 68 + "╣")
        lines.append("║ 💡 التوصيات:                                                 ║")
        
        for i, rec in enumerate(self.recommendations[:5], 1):
            lines.append(f"║  {i}. {rec[:60]:<62}  ║")
        
        lines.append("╚" + "═" * 68 + "╝")
        
        return "\n".join(lines)


class IntelligenceAgency:
    """
    وكالة الاستخبارات المركزية
    
    المهام:
    - إدارة شبكة الجواسيس
    - جمع المعلومات
    - تحليل الأداء
    - إصدار التقارير للقائد
    - كشف التجاوزات
    """
    
    # أرقام التقارير
    _report_counter = 0
    
    def __init__(self, base_dir, commander_id: str = "supreme_commander"):
        self.base_dir = Path(base_dir) / ".nova" / "intelligence"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.commander_id = commander_id
        self.spy_network = SpyNetwork()
        self.analyst = Analyst("analyst_001")
        
        # سجل التقارير
        self.reports: List[Report] = []
        self.pending_reports: List[Report] = []  # للقائد
        
        # سجلات من مصادر أخرى
        self.registry = None      # PersonnelRegistry
        self.guard = None         # HallucinationGuard
        self.monitor = None       # AgentMonitor
        
        # المستويات
        self.alert_level = ThreatLevel.GREEN
        
        logger.info(f"Intelligence Agency initialized (base={base_dir})")
    
    def connect_registry(self, registry):
        """اربط السجل الرسمي"""
        self.registry = registry
        logger.info("Registry connected")
    
    def connect_guard(self, guard):
        """اربط حارس الهلوسة"""
        self.guard = guard
        logger.info("Hallucination guard connected")
    
    def connect_monitor(self, monitor):
        """اربط مراقب الأداء"""
        self.monitor = monitor
        logger.info("Agent monitor connected")
    
    # ═══════════════════════════════════════════════════════
    # إدارة الجواسيس
    # ═══════════════════════════════════════════════════════
    
    def deploy_spy(
        self,
        spy_id: str,
        spy_type: SpyType,
        targets: List[str],
    ) -> Spy:
        """انشر جاسوساً جديداً"""
        spy = self.spy_network.create_spy(spy_id, spy_type, targets)
        logger.info(f"🕵️ Deployed {spy_id} ({spy_type.value}) → {len(targets)} targets")
        return spy
    
    def recall_spy(self, spy_id: str):
        """استدعِ جاسوساً"""
        if spy_id in self.spy_network.spies:
            self.spy_network.spies[spy_id].stop_coverage()
    
    # ═══════════════════════════════════════════════════════
    # توليد التقارير
    # ═══════════════════════════════════════════════════════
    
    def _next_report_id(self) -> str:
        """رقم تقرير جديد"""
        IntelligenceAgency._report_counter += 1
        return f"INT-{int(time.time())}-{IntelligenceAgency._report_counter:04d}"
    
    def generate_agent_report(self, target_id: str) -> Report:
        """تقرير عن وكيل واحد"""
        logger.info(f"Generating agent report for {target_id}...")
        
        # اجمع البيانات
        profile = self.registry.get(target_id) if self.registry else None
        hall = self.guard.get_record(target_id) if self.guard else None
        observations = self.spy_network.all_observations(target_id=target_id)
        
        # حلل
        analysis = self.analyst.analyze_agent(
            target_id=target_id,
            observations=observations,
            hall_record=hall,
            profile=profile,
        )
        
        # أنشئ التقرير
        findings = []
        for finding in analysis.findings:
            findings.append({
                "description": finding,
                "target": target_id,
            })
        
        report = Report(
            report_id=self._next_report_id(),
            report_type=ReportType.PERFORMANCE,
            classification=ReportClassification.CONFIDENTIAL,
            title=f"تقرير أداء — {profile.name if profile else target_id}",
            summary=self._build_summary(profile, hall, analysis),
            findings=findings,
            recommendations=analysis.recommendations,
            threat_level=analysis.threat_level,
            target_ids=[target_id],
            generated_at=time.time(),
        )
        
        self.reports.append(report)
        self.pending_reports.append(report)
        
        return report
    
    def _build_summary(self, profile, hall, analysis) -> str:
        """ملخص نصي"""
        parts = []
        if profile:
            parts.append(f"الوكيل: {profile.name} ({profile.rank.arabic_name})")
            parts.append(f"الفرع: {profile.branch.arabic_name}")
            parts.append(f"نسبة النجاح: {profile.success_rate * 100:.1f}%")
        if hall:
            parts.append(f"نقاط الهلوسة: {hall.weighted_score}")
            parts.append(f"مستوى الثقة: {hall.trust_level * 100:.1f}%")
        parts.append(f"مستوى التهديد: {analysis.threat_level.arabic}")
        return " | ".join(parts)
    
    def generate_daily_report(self) -> Report:
        """تقرير يومي شامل"""
        logger.info("Generating daily intelligence report...")
        
        # كل الملاحظات الأخيرة
        all_obs = self.spy_network.all_observations()
        recent = [o for o in all_obs if time.time() - o.timestamp < 86400]
        
        # تحليل الأنماط
        patterns = self.analyst.analyze_patterns(recent)
        
        # اجمع التهديدات
        findings = []
        recommendations = []
        threat_score = 0
        
        # 1. هلوسة عالية
        if self.guard:
            for agent_id, record in self.guard.records.items():
                if record.weighted_score >= 15:
                    findings.append({
                        "description": f"🚨 {agent_id}: {record.weighted_score} نقطة هلوسة",
                        "target": agent_id,
                    })
                    recommendations.append(f"إعادة تدريب {agent_id}")
                    threat_score += 3
        
        # 2. أداء منخفض
        if self.registry:
            for agent_id, profile in self.registry.profiles.items():
                if profile.success_rate < 0.5 and (profile.missions_completed + profile.missions_failed) > 5:
                    findings.append({
                        "description": f"⚠️ {agent_id}: نجاح {profile.success_rate*100:.0f}%",
                        "target": agent_id,
                    })
                    threat_score += 1
        
        # 3. ملاحظات حرجة
        critical = [o for o in recent if o.severity == "critical"]
        if critical:
            findings.append({
                "description": f"🚨 {len(critical)} حادثة خطيرة",
                "target": "multiple",
            })
            threat_score += 4
        
        # حدد التهديد العام
        if threat_score >= 8:
            level = ThreatLevel.BLACK
        elif threat_score >= 5:
            level = ThreatLevel.RED
        elif threat_score >= 3:
            level = ThreatLevel.ORANGE
        elif threat_score >= 1:
            level = ThreatLevel.YELLOW
        else:
            level = ThreatLevel.GREEN
        
        self.alert_level = level
        
        report = Report(
            report_id=self._next_report_id(),
            report_type=ReportType.DAILY,
            classification=ReportClassification.TOP_SECRET,
            title="التقرير اليومي للاستخبارات",
            summary=f"تم رصد {len(recent)} ملاحظة في 24 ساعة | مستوى التهديد: {level.arabic}",
            findings=findings,
            recommendations=recommendations,
            threat_level=level,
            target_ids=list(set(f.get("target", "") for f in findings)),
        )
        
        self.reports.append(report)
        self.pending_reports.append(report)
        
        return report
    
    # ═══════════════════════════════════════════════════════
    # تسليم التقارير للقائد
    # ═══════════════════════════════════════════════════════
    
    def deliver_to_commander(self) -> List[Report]:
        """سلّم التقارير المعلّقة للقائد"""
        pending = self.pending_reports.copy()
        self.pending_reports.clear()
        
        for report in pending:
            logger.info(f"📤 Delivered to commander: {report.report_id}")
        
        return pending
    
    # ═══════════════════════════════════════════════════════
    # استقبال معلومات من الجواسيس
    # ═══════════════════════════════════════════════════════
    
    def receive_observation(
        self,
        spy_id: str,
        target_id: str,
        obs_type: str,
        description: str,
        severity: str = "info",
        evidence: Optional[Dict] = None,
    ):
        """استقبل ملاحظة من جاسوس"""
        obs = self.spy_network.observe(
            spy_id, target_id, obs_type, description, severity, evidence
        )
        
        # إذا كانت خطيرة، أنشئ تقريراً فورياً
        if severity in ("alert", "critical"):
            self._create_incident_report(obs)
    
    def _create_incident_report(self, obs: Observation):
        """أنشئ تقرير حادثة فوري"""
        report = Report(
            report_id=self._next_report_id(),
            report_type=ReportType.INCIDENT,
            classification=ReportClassification.SECRET,
            title=f"حادثة أمنية — {obs.target_id}",
            summary=obs.description,
            findings=[obs.to_dict()],
            recommendations=["تحقيق فوري", "إبلاغ القائد"],
            threat_level=ThreatLevel.RED if obs.severity == "critical" else ThreatLevel.ORANGE,
            target_ids=[obs.target_id],
            generated_at=time.time(),
        )
        
        self.reports.append(report)
        self.pending_reports.append(report)
        
        logger.warning(f"🚨 Incident report: {report.report_id}")
    
    # ═══════════════════════════════════════════════════════
    # الإحصائيات
    # ═══════════════════════════════════════════════════════
    
    def stats(self) -> Dict:
        """إحصائيات الوكالة"""
        return {
            "spy_network": self.spy_network.stats(),
            "reports_generated": len(self.reports),
            "pending_for_commander": len(self.pending_reports),
            "alert_level": self.alert_level.arabic,
            "analyses_performed": len(self.analyst.analyses),
        }
