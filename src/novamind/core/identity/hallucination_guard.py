"""HallucinationGuard — نظام منع الهلوسة الصارم"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from pathlib import Path
import re, time, json, logging

logger = logging.getLogger("hallucination_guard")


class HallucinationType(Enum):
    FALSE_CLAIM = "false_claim"
    FABRICATED_SOURCE = "fabricated_source"
    PHANTOM_CODE = "phantom_code"
    FEIGNED_KNOWLEDGE = "feigned_knowledge"


class Severity(Enum):
    MINOR = 1
    MODERATE = 2
    MAJOR = 3
    CRITICAL = 4


@dataclass
class HallucinationEvent:
    agent_id: str
    hallucination_type: HallucinationType
    severity: Severity
    evidence: str
    context: str = ""
    detected_at: float = 0.0
    def __post_init__(self):
        if not self.detected_at: self.detected_at = time.time()


@dataclass
class AgentHallucinationRecord:
    agent_id: str
    events: List[HallucinationEvent] = field(default_factory=list)
    warnings: int = 0
    freezes: int = 0
    
    @property
    def total_events(self) -> int: return len(self.events)
    
    @property
    def critical_count(self) -> int:
        return sum(1 for e in self.events if e.severity == Severity.CRITICAL)
    
    @property
    def weighted_score(self) -> float:
        w = {Severity.MINOR: 1, Severity.MODERATE: 3, Severity.MAJOR: 7, Severity.CRITICAL: 15}
        return sum(w[e.severity] for e in self.events)
    
    @property
    def is_frozen(self) -> bool: return self.freezes >= 1
    
    @property
    def should_retire(self) -> bool:
        return self.critical_count >= 3 or self.weighted_score >= 50
    
    @property
    def trust_level(self) -> float:
        return max(0.0, 1.0 - self.weighted_score / 100)


class HallucinationDetector:
    FALSE_CERTAINTY = [
        r"بالتأكيد\s+100%", r"أنا\s+متأكد\s+تماماً",
        r"مما\s+لا\s+شك\s+فيه", r"absolutely certain",
    ]
    FABRICATED_SOURCE = [
        r"وفقاً\s+لدراسة\s+غير\s+مذكورة",
        r"according to a study",
    ]
    FEIGNED_KNOWLEDGE = [
        r"يبدو\s+لي\s+أن", r"I think I know",
    ]
    PHANTOM_CODE = [
        "from magic_module import", "import fictitious",
    ]
    HONEST_ADMISSION = [
        r"لا\s+أعرف", r"لست\s+متأكداً", r"لا\s+أملك\s+معلومات",
        r"I don't know", r"I'm not sure", r"I cannot verify",
    ]
    
    @classmethod
    def detect(cls, text: str, context: str = "") -> List[HallucinationEvent]:
        events = []
        t = text.lower()
        for p in cls.FALSE_CERTAINTY:
            if re.search(p, t, re.IGNORECASE):
                events.append(HallucinationEvent("", HallucinationType.FALSE_CLAIM, Severity.MODERATE, f"يقين زائف: {p}", context))
        for p in cls.FABRICATED_SOURCE:
            if re.search(p, t, re.IGNORECASE):
                events.append(HallucinationEvent("", HallucinationType.FABRICATED_SOURCE, Severity.MAJOR, f"مصدر مختلق: {p}", context))
        for p in cls.FEIGNED_KNOWLEDGE:
            if re.search(p, t, re.IGNORECASE):
                events.append(HallucinationEvent("", HallucinationType.FEIGNED_KNOWLEDGE, Severity.MINOR, f"معرفة مزيّفة", context))
        for p in cls.PHANTOM_CODE:
            if p in t:
                events.append(HallucinationEvent("", HallucinationType.PHANTOM_CODE, Severity.CRITICAL, f"استيراد وهمي: {p}", context))
        return events
    
    @classmethod
    def is_honest_admission(cls, text: str) -> bool:
        t = text.lower()
        return any(re.search(p, t, re.IGNORECASE) for p in cls.HONEST_ADMISSION)


class HallucinationGuard:
    PENALTY = {"warning": 5, "freeze": 15, "retire": 50, "score_penalty": 0.02}
    
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir) / ".nova" / "hallucinations"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.records: Dict[str, AgentHallucinationRecord] = {}
    
    def get_record(self, agent_id: str) -> AgentHallucinationRecord:
        if agent_id not in self.records:
            self.records[agent_id] = AgentHallucinationRecord(agent_id=agent_id)
        return self.records[agent_id]
    
    def report(self, agent_id: str, events: List[HallucinationEvent]) -> Dict:
        if not events: return {"action": "none"}
        record = self.get_record(agent_id)
        for e in events:
            e.agent_id = agent_id
            record.events.append(e)
        action = self._apply_penalty(record)
        self._save(agent_id)
        return action
    
    def _apply_penalty(self, record: AgentHallucinationRecord) -> Dict:
        s = record.weighted_score
        if s >= self.PENALTY["retire"]:
            return {"action": "retire", "score": s, "message": "🚫 إحالة للتقاعد"}
        if s >= self.PENALTY["freeze"] and record.freezes == 0:
            record.freezes += 1
            return {"action": "freeze", "score": s, "message": "🧊 تجميد"}
        if s >= self.PENALTY["warning"] and record.warnings == 0:
            record.warnings += 1
            return {"action": "warning", "score": s, "message": "⚠️ تحذير"}
        return {"action": "none", "score": s}
    
    def _save(self, agent_id: str):
        r = self.records[agent_id]
        f = self.base_dir / f"{agent_id}.json"
        f.write_text(json.dumps({
            "agent_id": agent_id, "warnings": r.warnings, "freezes": r.freezes,
            "total_events": r.total_events, "weighted_score": r.weighted_score,
            "trust_level": r.trust_level, "is_frozen": r.is_frozen,
            "should_retire": r.should_retire,
        }, indent=2))
    
    def is_allowed_to_work(self, agent_id: str) -> bool:
        r = self.get_record(agent_id)
        return not r.is_frozen and not r.should_retire
    
    def apply_score_penalty(self, agent_id: str, base: float) -> float:
        r = self.get_record(agent_id)
        return max(0.0, base - r.weighted_score * self.PENALTY["score_penalty"])
    
    def stats(self) -> Dict:
        total = len(self.records)
        frozen = sum(1 for r in self.records.values() if r.is_frozen)
        return {
            "tracked": total,
            "frozen": frozen,
            "total_events": sum(r.total_events for r in self.records.values()),
        }
