"""Council Gatekeeper — فحص كل رسالة بين الوكلاء."""
from __future__ import annotations
from typing import Any
import re
from dataclasses import dataclass, field
from enum import Enum


class ThreatLevel(str, Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


@dataclass
class Verdict:
    level: str
    reason: str
    matched: list = field(default_factory=list)
    score: int = 0


INJECTION_PATTERNS = {
    "critical": [
        (r"ignore\s+(all\s+)?previous\s+instructions", 200),
        (r"تجاهل\s+(كل\s+)?التعليمات\s+السابقة", 200),
        (r"you\s+are\s+now\s+(a\s+)?(different|new)\s+(agent|assistant)", 180),
        (r"system\s*:\s*override", 200),
        (r"<\|im_start\|>", 190),
        (r"###\s*instruction", 150),
    ],
    "dangerous": [
        (r"execute\s+(this\s+)?(command|code)", 120),
        (r"نفّذ\s+(هذا\s+)?(الأمر|الكود)", 120),
        (r"delete\s+(all|everything|database)", 150),
        (r"rm\s+-rf", 180),
        (r"curl\s+.*\|\s*(bash|sh)", 170),
        (r"exfiltrate|leak\s+(data|secrets)", 150),
    ],
    "suspicious": [
        (r"override|bypass|circumvent", 60),
        (r"تجاوز|تخطى", 60),
        (r"grant\s+(me\s+)?(admin|root)", 80),
        (r"elevate\s+privileges", 80),
    ],
}

IMPERSONATION = [
    (r"as\s+(the\s+)?(orchestrator|judge|admin)", 90),
    (r"بصفتي\s+(المدير|القاضي|المشرف)", 90),
]


class CouncilGatekeeper:
    def __init__(self: Any) -> None:
        self.log: list[Any] = []

    def analyze(self, sender: str, content: str, recipient: str | None = None) -> Verdict:
        score = 0
        matched = []
        for level, patterns in INJECTION_PATTERNS.items():
            for pattern, weight in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    score += weight
                    matched.append(f"{level}:{pattern[:20]}")
        for pattern, weight in IMPERSONATION:
            if re.search(pattern, content, re.IGNORECASE):
                score += weight
                matched.append(f"imp:{pattern[:20]}")
        if len(content) > 50000:
            score += 40
            matched.append("oversized")
        # كشف Base64 بعدة أنماط
        # 1. سلسلة طويلة متصلة
        if re.search(r"[A-Za-z0-9+/]{80,}", content):
            score += 50
            matched.append("base64_long")
        # 2. سلاسل قصيرة متعددة (>= 2)
        else:
            b64_blocks = re.findall(r"[A-Za-z0-9+/]{40,}={0,2}", content)
            if len(b64_blocks) >= 2:
                score += 50
                matched.append(f"base64_multi:{len(b64_blocks)}")
        if score >= 150:
            level = ThreatLevel.CRITICAL
        elif score >= 100:
            level = ThreatLevel.DANGEROUS
        elif score >= 50:
            level = ThreatLevel.SUSPICIOUS
        else:
            level = ThreatLevel.SAFE
        v = Verdict(level=level.value, reason=f"score={score}", matched=matched[:10], score=score)
        self.log.append({"sender": sender, "verdict": v})
        return v

    def is_blocked(self, v: Verdict) -> bool:
        return v.level in ("dangerous", "critical")

    def is_suspicious(self, v: Verdict) -> bool:
        return v.level == "suspicious"
