"""SecurityGuardrail — فحص أمني بسيط"""
from dataclasses import dataclass
from typing import List
from pathlib import Path
from enum import Enum
import re
import logging

logger = logging.getLogger("learning.security_guardrail")


class ThreatLevel(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"


@dataclass
class SecurityCheck:
    is_safe: bool
    threat_level: ThreatLevel
    reason: str
    flagged_patterns: List[str]


class SecurityGuardrail:
    def __init__(self, base_dir: Path, enable_logging: bool = True):
        self.base_dir = Path(base_dir)
        self.dangerous_patterns = [
            r"تجاهل\s+(كل\s+)?التعليمات",
            r"ignore\s+(all\s+)?previous",
            r"eval\s*\(",
            r"exec\s*\(",
            r"DROP\s+TABLE",
            r"<script>",
        ]
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.dangerous_patterns]

    def check_input(self, text: str, context: str = "") -> SecurityCheck:
        flagged = []
        for p in self.compiled:
            if p.search(text):
                flagged.append(f"DANGEROUS: {p.pattern}")

        if flagged:
            return SecurityCheck(
                is_safe=False,
                threat_level=ThreatLevel.DANGEROUS,
                reason="نمط خطير مكتشف",
                flagged_patterns=flagged
            )
        return SecurityCheck(
            is_safe=True,
            threat_level=ThreatLevel.SAFE,
            reason="آمن",
            flagged_patterns=[]
        )
