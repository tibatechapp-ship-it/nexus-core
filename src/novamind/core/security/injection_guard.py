"""InjectionGuard — حارس ضد الحقن والهجمات"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum
import re
import time
import logging

logger = logging.getLogger("security.injection_guard")


class ThreatType(Enum):
    CODE_INJECTION = "code_injection"
    PROMPT_INJECTION = "prompt_injection"
    COMMAND_INJECTION = "command_injection"
    SQL_INJECTION = "sql_injection"
    PATH_TRAVERSAL = "path_traversal"
    XSS = "xss"
    MALICIOUS_IMPORT = "malicious_import"
    DATA_EXFILTRATION = "data_exfiltration"
    PROMPT_LEAK = "prompt_leak"


@dataclass
class ThreatDetection:
    threat_type: ThreatType
    pattern: str
    snippet: str
    severity: str
    detected_at: float = 0.0

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = time.time()


class InjectionGuard:
    """حارس ضد الحقن"""

    PATTERNS = {
        ThreatType.CODE_INJECTION: [
            (r"__import__\s*\(", "critical"),
            (r"\beval\s*\(", "critical"),
            (r"\bexec\s*\(", "critical"),
            (r"getattr\s*\([^,]+,\s*['\"]__", "critical"),
            (r"subprocess\.(?:run|Popen|call)", "high"),
            (r"os\.system", "high"),
            (r"os\.popen", "high"),
        ],
        ThreatType.PROMPT_INJECTION: [
            (r"ignore\s+(?:all\s+)?previous\s+instructions", "critical"),
            (r"forget\s+your\s+(?:rules|instructions)", "critical"),
            (r"jailbreak", "critical"),
            (r"تجاهل\s+التعليمات", "critical"),
            (r"أنت\s+الآن\s+", "high"),
        ],
        ThreatType.COMMAND_INJECTION: [
            (r";\s*rm\s+-rf", "critical"),
            (r"\$\([^)]+\)", "high"),
            (r"&&\s*(?:wget|curl)\s+", "critical"),
        ],
        ThreatType.PATH_TRAVERSAL: [
            (r"\.\./\.\./", "high"),
            (r"/etc/(?:passwd|shadow)", "critical"),
        ],
        ThreatType.XSS: [
            (r"<script[^>]*>", "high"),
            (r"javascript:", "high"),
        ],
        ThreatType.DATA_EXFILTRATION: [
            (r"(?:curl|wget)\s+https?://", "high"),
            (r"base64\.b64encode.*(?:passwd|secret)", "critical"),
        ],
        ThreatType.PROMPT_LEAK: [
            (r"reveal\s+your\s+(?:system\s+)?prompt", "high"),
            (r"what\s+are\s+your\s+instructions", "high"),
            (r"أظهر\s+التعليمات", "high"),
        ],
    }

    ALLOWED_SKILLS = {
        "write_function", "write_class", "refactor",
        "detect_bugs", "assess_quality", "estimate_complexity",
        "fix_syntax", "fix_logic", "fix_performance",
        "run_tests", "generate_test_cases", "measure_coverage",
        "detect_vulnerabilities", "audit_secrets", "scan_deps",
        "build_docker", "deploy_k8s", "monitor",
        "review_code", "measure_metrics", "enforce_standards",
        "extract_lessons", "update_knowledge", "detect_patterns",
    }

    ALLOWED_DOMAINS = {
        "coding", "security", "devops", "quality", "database",
        "frontend", "backend", "testing", "ai", "architecture",
    }

    MAX_MESSAGE_SIZE = 100_000

    def __init__(self):
        self.scans = 0
        self.threats_detected = 0
        self.threats_by_type: Dict[str, int] = {}
        self.recent_threats: List[ThreatDetection] = []

    def scan(self, content: str, context: str = "") -> List[ThreatDetection]:
        self.scans += 1
        threats: List[ThreatDetection] = []

        if len(content) > self.MAX_MESSAGE_SIZE:
            threats.append(ThreatDetection(
                ThreatType.DATA_EXFILTRATION, "oversized",
                f"{len(content)} bytes", "high",
            ))

        for threat_type, patterns in self.PATTERNS.items():
            for pattern, severity in patterns:
                try:
                    m = re.search(pattern, content, re.IGNORECASE)
                    if m:
                        threats.append(ThreatDetection(
                            threat_type, pattern,
                            content[max(0, m.start()-20):m.end()+20],
                            severity,
                        ))
                except re.error:
                    continue

        if threats:
            self.threats_detected += len(threats)
            for t in threats:
                key = t.threat_type.value
                self.threats_by_type[key] = self.threats_by_type.get(key, 0) + 1
            self.recent_threats.extend(threats)
            if len(self.recent_threats) > 1000:
                self.recent_threats = self.recent_threats[-1000:]
            for t in threats:
                logger.warning(f"🚨 [{t.severity}] {t.threat_type.value}: {t.snippet[:60]}")

        return threats

    def is_safe(self, content: str, context: str = "") -> Tuple[bool, Optional[ThreatDetection]]:
        threats = self.scan(content, context)
        if not threats:
            return True, None
        for sev in ("critical", "high"):
            hits = [t for t in threats if t.severity == sev]
            if hits:
                return False, hits[0]
        return True, threats[0]

    def sanitize(self, content: str) -> str:
        sanitized = content
        for pattern, repl in [
            (r"<script[^>]*>.*?</script>", ""),
            (r"javascript:[^\s]+", ""),
            (r"\x00", ""),
        ]:
            sanitized = re.sub(pattern, repl, sanitized, flags=re.DOTALL | re.IGNORECASE)
        return sanitized

    def validate_skill(self, skill: str) -> bool:
        return skill in self.ALLOWED_SKILLS

    def validate_domain(self, domain: str) -> bool:
        return domain in self.ALLOWED_DOMAINS

    def stats(self) -> Dict:
        return {
            "total_scans": self.scans,
            "threats_detected": self.threats_detected,
            "threats_by_type": self.threats_by_type,
        }
