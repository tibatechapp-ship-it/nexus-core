"""
Spy — الجاسوس
كل جاسوس يرصد وكيلاً أو مجموعة وكلاء
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import time
import logging
import json
from pathlib import Path

logger = logging.getLogger("intelligence.spy")


class SpyType(Enum):
    """أنواع الجواسيس"""
    COUNTER = "counter"           # رصد عادي
    AUDITOR = "auditor"           # مدقق مالي/أدائي
    MONITOR = "monitor"           # مراقب مباشر
    INFILTRATOR = "infiltrator"   # متمركز داخل مجموعة
    DEEP_COVER = "deep_cover"     # عميل عميق


@dataclass
class Observation:
    """ملاحظة واحدة من الجاسوس"""
    timestamp: float
    spy_id: str
    target_id: str
    observation_type: str
    severity: str  # info / warning / alert / critical
    description: str
    evidence: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "spy_id": self.spy_id,
            "target_id": self.target_id,
            "type": self.observation_type,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
        }


class Spy:
    """
    جاسوس واحد
    - يرصد وكيلاً أو أكثر
    - يسجّل كل ملاحظة
    - يرسل التنبيهات للأجهزة
    """
    
    def __init__(self, spy_id: str, spy_type: SpyType = SpyType.COUNTER):
        self.spy_id = spy_id
        self.spy_type = spy_type
        self.targets: List[str] = []
        self.observations: List[Observation] = []
        self.active = True
        self.coverage_start: Optional[float] = None
        
        logger.info(f"Spy {spy_id} ({spy_type.value}) created")
    
    def assign_target(self, target_id: str):
        """عيّن هدفاً للمراقبة"""
        if target_id not in self.targets:
            self.targets.append(target_id)
            logger.info(f"  {self.spy_id} → watching {target_id}")
    
    def start_coverage(self):
        """ابدأ المراقبة"""
        self.coverage_start = time.time()
        self.active = True
        logger.info(f"  {self.spy_id} coverage started")
    
    def stop_coverage(self):
        """أوقف المراقبة"""
        self.active = False
        logger.info(f"  {self.spy_id} coverage stopped")
    
    def observe(
        self,
        target_id: str,
        observation_type: str,
        description: str,
        severity: str = "info",
        evidence: Optional[Dict] = None,
    ) -> Observation:
        """سجّل ملاحظة"""
        obs = Observation(
            timestamp=time.time(),
            spy_id=self.spy_id,
            target_id=target_id,
            observation_type=observation_type,
            severity=severity,
            description=description,
            evidence=evidence or {},
        )
        self.observations.append(obs)
        
        if severity in ("alert", "critical"):
            logger.warning(f"  🚨 {self.spy_id} [{severity}] {target_id}: {description}")
        
        return obs
    
    def report(self) -> Dict:
        """تقرير الجاسوس"""
        return {
            "spy_id": self.spy_id,
            "type": self.spy_type.value,
            "active": self.active,
            "targets": self.targets,
            "coverage_hours": (time.time() - self.coverage_start) / 3600 if self.coverage_start else 0,
            "total_observations": len(self.observations),
            "by_severity": self._count_by_severity(),
            "recent": [o.to_dict() for o in self.observations[-10:]],
        }
    
    def _count_by_severity(self) -> Dict:
        counts = {"info": 0, "warning": 0, "alert": 0, "critical": 0}
        for o in self.observations:
            counts[o.severity] = counts.get(o.severity, 0) + 1
        return counts


class SpyNetwork:
    """
    شبكة الجواسيس
    - تدير كل الجواسيس
    - توزع المهام
    - تجمع التقارير
    """
    
    def __init__(self):
        self.spies: Dict[str, Spy] = {}
        self.target_to_spies: Dict[str, List[str]] = {}  # target -> [spy_ids]
    
    def create_spy(
        self,
        spy_id: str,
        spy_type: SpyType = SpyType.COUNTER,
        targets: Optional[List[str]] = None,
    ) -> Spy:
        """أنشئ جاسوساً جديداً"""
        spy = Spy(spy_id, spy_type)
        self.spies[spy_id] = spy
        
        for target in (targets or []):
            spy.assign_target(target)
            self.target_to_spies.setdefault(target, []).append(spy_id)
        
        spy.start_coverage()
        return spy
    
    def get_spies_for(self, target_id: str) -> List[Spy]:
        """احصل على الجواسيس المراقبين لهدف"""
        spy_ids = self.target_to_spies.get(target_id, [])
        return [self.spies[sid] for sid in spy_ids if sid in self.spies]
    
    def observe(
        self,
        spy_id: str,
        target_id: str,
        observation_type: str,
        description: str,
        severity: str = "info",
        evidence: Optional[Dict] = None,
    ) -> Optional[Observation]:
        """سجّل ملاحظة عبر جاسوس"""
        if spy_id not in self.spies:
            return None
        return self.spies[spy_id].observe(
            target_id, observation_type, description, severity, evidence
        )
    
    def all_observations(self, target_id: Optional[str] = None, severity: Optional[str] = None) -> List[Observation]:
        """احصل على كل الملاحظات (مع فلترة اختيارية)"""
        result = []
        for spy in self.spies.values():
            for obs in spy.observations:
                if target_id and obs.target_id != target_id:
                    continue
                if severity and obs.severity != severity:
                    continue
                result.append(obs)
        return sorted(result, key=lambda o: o.timestamp, reverse=True)
    
    def stats(self) -> Dict:
        """إحصائيات الشبكة"""
        total_obs = sum(len(s.observations) for s in self.spies.values())
        by_severity = {"info": 0, "warning": 0, "alert": 0, "critical": 0}
        for spy in self.spies.values():
            for obs in spy.observations:
                by_severity[obs.severity] = by_severity.get(obs.severity, 0) + 1
        
        return {
            "total_spies": len(self.spies),
            "active_spies": sum(1 for s in self.spies.values() if s.active),
            "total_targets": len(self.target_to_spies),
            "total_observations": total_obs,
            "by_severity": by_severity,
        }
