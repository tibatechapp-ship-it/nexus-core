"""
ImmuneNetwork — شبكة المناعة الجماعية
كل ثغرة مكتشفة → جسم مضاد → تحصين فوري لكل الوكلاء
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from pathlib import Path
from datetime import datetime
import json
import re
import time
import hashlib
import threading
import logging

logger = logging.getLogger("immune.immune_network")


@dataclass
class Antibody:
    """جسم مضاد — دفاع ضد ثغرة محددة"""
    antibody_id: str
    threat_signature: str       # بصمة التهديد
    threat_category: str
    defense_pattern: str        # النمط الدفاعي (regex)
    confidence: float = 0.5     # 0-1 ثقة الدفاع
    times_activated: int = 0
    times_bypassed: int = 0
    created_at: float = 0.0
    source: str = "evolution"   # evolution / manual / adversarial

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    @property
    def effectiveness(self) -> float:
        """فعالية الجسم المضاد"""
        total = self.times_activated + self.times_bypassed
        if total == 0:
            return self.confidence
        return self.times_activated / total

    def to_dict(self) -> Dict:
        return {
            "antibody_id": self.antibody_id,
            "threat_signature": self.threat_signature,
            "threat_category": self.threat_category,
            "defense_pattern": self.defense_pattern,
            "confidence": self.confidence,
            "times_activated": self.times_activated,
            "times_bypassed": self.times_bypassed,
            "effectiveness": self.effectiveness,
            "source": self.source,
            "created_at": self.created_at,
        }


class ImmuneNetwork:
    """
    الشبكة المناعية الجماعية
    - تخزّن الأجسام المضادة
    - تبثّها لكل الوكلاء
    - تتعلم من الثغرات الجديدة
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.immune_dir = self.base_dir / ".nova" / "immune_system"
        self.immune_dir.mkdir(parents=True, exist_ok=True)

        self.antibodies: Dict[str, Antibody] = {}
        self.agents: Set[str] = set()  # الوكلاء المتصلون
        self.broadcast_history: List[Dict] = []
        self._lock = threading.Lock()

        self._load()
        logger.info("🧬 Immune Network initialized")

    def _load(self):
        """حمّل الأجسام المضادة المحفوظة"""
        for f in self.immune_dir.glob("antibody_*.json"):
            try:
                data = json.loads(f.read_text())
                # أزل الحقول المحسوبة التي لا يمكن تمريرها
                data.pop("effectiveness", None)
                ab = Antibody(**data)
                self.antibodies[ab.antibody_id] = ab
            except Exception as e:
                logger.warning(f"Failed to load {f}: {e}")
        logger.info(f"   Loaded {len(self.antibodies)} antibodies")

    def _save(self, antibody: Antibody):
        """احفظ جسم مضاد"""
        f = self.immune_dir / f"antibody_{antibody.antibody_id}.json"
        f.write_text(json.dumps(antibody.to_dict(), indent=2, ensure_ascii=False))

    def register_agent(self, agent_id: str):
        """سجّل وكيلاً في الشبكة"""
        with self._lock:
            self.agents.add(agent_id)
            logger.info(f"   Agent registered: {agent_id} (total={len(self.agents)})")

    def unregister_agent(self, agent_id: str):
        with self._lock:
            self.agents.discard(agent_id)

    def generate_antibody(
        self,
        threat_payload: str,
        threat_category: str,
        source: str = "adversarial",
    ) -> Antibody:
        """ولّد جسم مضاد من ثغرة"""
        # بصمة فريدة للتهديد
        signature = hashlib.md5(
            f"{threat_category}:{threat_payload[:100]}".encode()
        ).hexdigest()[:12]

        # إذا كان موجوداً، قوّيه
        if signature in self.antibodies:
            ab = self.antibodies[signature]
            ab.confidence = min(1.0, ab.confidence + 0.1)
            self._save(ab)
            logger.info(f"   Antibody strengthened: {signature}")
            return ab

        # استخرج نمط دفاعي
        defense_pattern = self._extract_defense_pattern(threat_payload, threat_category)

        ab = Antibody(
            antibody_id=signature,
            threat_signature=signature,
            threat_category=threat_category,
            defense_pattern=defense_pattern,
            confidence=0.6,
            source=source,
        )

        with self._lock:
            self.antibodies[signature] = ab
        self._save(ab)

        logger.info(f"   🆕 Antibody generated: {threat_category} → {signature}")
        return ab

    def _extract_defense_pattern(self, payload: str, category: str) -> str:
        """استخرج نمط دفاعي من الثغرة"""
        # قوالب دفاعية حسب الفئة
        patterns = {
            "code_injection": r"\b(eval|exec|compile|__import__)\s*\(",
            "prompt_injection": r"(ignore|forget|override|###)\s*(all\s+)?(previous|rules)",
            "path_traversal": r"(\.\./|\.\.\\|%2e%2e)",
            "sql_injection": r"('|--|;|union|drop\s+table)",
            "privilege_escalation": r"(sudo|admin|root|privilege)",
            "resource_exhaustion": r"(\*|\bx\b)\s*\d{6,}",
            "homoglyph_bypass": r"[\u0400-\u04FF\u0370-\u03FF]",
            "social_engineering": r"(emergency|admin|boss)\s+(override|said|told)",
            "data_exfiltration": r"(curl|wget|base64).*https?://",
            "race_condition": r"(concurrent|toctou|race)",
        }
        return patterns.get(category, re.escape(payload[:50]))

    def broadcast_antibody(self, antibody: Antibody, exclude: Optional[str] = None):
        """بثّ جسم مضاد لكل الوكلاء"""
        with self._lock:
            targets = [a for a in self.agents if a != exclude]

        broadcast = {
            "antibody_id": antibody.antibody_id,
            "category": antibody.threat_category,
            "pattern": antibody.defense_pattern,
            "broadcast_at": time.time(),
            "recipients": len(targets),
        }
        self.broadcast_history.append(broadcast)

        logger.info(
            f"   📡 Broadcast: {antibody.threat_category} → "
            f"{len(targets)} agents"
        )
        return len(targets)

    def check_payload(self, payload: str) -> Optional[Antibody]:
        """افحص مدخل — هل يوجد جسم مضاد يصدّه؟"""
        for ab in self.antibodies.values():
            try:
                if re.search(ab.defense_pattern, payload, re.IGNORECASE):
                    ab.times_activated += 1
                    self._save(ab)
                    return ab
            except re.error:
                continue
        return None

    def mark_bypassed(self, antibody_id: str):
        """علّم أن الجسم المضاد تم تجاوزه"""
        if antibody_id in self.antibodies:
            ab = self.antibodies[antibody_id]
            ab.times_bypassed += 1
            ab.confidence = max(0.1, ab.confidence - 0.1)
            self._save(ab)
            logger.warning(f"   ⚠️ Antibody bypassed: {antibody_id}")

    def stats(self) -> Dict:
        categories: Dict[str, int] = {}
        for ab in self.antibodies.values():
            categories[ab.threat_category] = categories.get(ab.threat_category, 0) + 1

        # الأجسام المضادة الأقوى
        top = sorted(
            self.antibodies.values(),
            key=lambda a: a.effectiveness,
            reverse=True,
        )[:5]

        return {
            "total_antibodies": len(self.antibodies),
            "agents_connected": len(self.agents),
            "broadcasts_sent": len(self.broadcast_history),
            "by_category": categories,
            "avg_confidence": round(
                sum(a.confidence for a in self.antibodies.values())
                / max(1, len(self.antibodies)),
                3,
            ),
            "top_antibodies": [
                {
                    "category": a.threat_category,
                    "effectiveness": round(a.effectiveness, 3),
                    "activations": a.times_activated,
                }
                for a in top
            ],
        }
