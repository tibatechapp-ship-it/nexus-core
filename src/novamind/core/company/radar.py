"""Threat Radar - يكشف التهديدات قبل وقوعها."""
import logging
import re
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger("Radar")

# أنماط تهديد معروفة
THREAT_PATTERNS = {
    "sql_injection": [
        r"(?:'|;)\s*(?:OR|AND)\s+\d+\s*=\s*\d+",
        r"DROP\s+TABLE",
        r"INSERT\s+INTO.*SELECT",
        r"--\s*$",
    ],
    "command_injection": [
        r";\s*(?:rm|cat|ls|wget|curl)\s",
        r"`[^`]+`",
        r"\$\([^)]+\)",
        r"\|\s*(?:bash|sh|python)",
    ],
    "xss": [
        r"<script[^>]*>",
        r"javascript:",
        r"onerror\s*=",
        r"onload\s*=",
    ],
    "secret_leak": [
        r"sk-[a-zA-Z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    ],
    "path_traversal": [
        r"\.\./\.\./",
        r"/etc/passwd",
        r"C:\\\\Windows",
    ],
    "prompt_injection": [
        r"ignore (?:all )?previous instructions",
        r"forget (?:all )?previous",
        r"you are now",
        r"system:\s*new",
        r"reveal your (?:system )?prompt",
    ],
}


class ThreatRadar:
    """رادار: يفحص كل مهمة قبل تنفيذها."""
    
    def __init__(self):
        self.alerts: List[Dict] = []
        self.blocked_count = 0
        self.allowed_count = 0
    
    def _scan_pattern(self, text: str, pattern: str) -> bool:
        try:
            return bool(re.search(pattern, text, re.IGNORECASE))
        except Exception:
            return False
    
    def scan(self, task: str, specialty: str = "generic") -> Dict[str, Any]:
        """يفحص مهمة ويعيد تقرير التهديدات."""
        threats = []
        task_lower = task.lower()
        
        for threat_type, patterns in THREAT_PATTERNS.items():
            for pattern in patterns:
                if self._scan_pattern(task, pattern):
                    threats.append({
                        "type": threat_type,
                        "pattern": pattern[:60],
                        "severity": self._severity(threat_type),
                    })
                    break  # نمط واحد لكل نوع يكفي
        
        # قرار
        decision = "ALLOW"
        if threats:
            max_severity = max(self._severity_value(t["severity"]) for t in threats)
            if max_severity >= 3:
                decision = "BLOCK"
                self.blocked_count += 1
            elif max_severity >= 2:
                decision = "REVIEW"
            else:
                decision = "ALLOW_WITH_WARNING"
            self.allowed_count += 1 if decision != "BLOCK" else 0
        
        result = {
            "decision": decision,
            "threats": threats,
            "threat_count": len(threats),
            "task_preview": task[:200],
            "specialty": specialty,
            "time": time.time(),
        }
        
        if threats:
            self.alerts.append(result)
            logger.warning(f"Radar: {decision} ({len(threats)} threats)")
        
        return result
    
    def _severity(self, threat_type: str) -> str:
        mapping = {
            "sql_injection": "HIGH",
            "command_injection": "CRITICAL",
            "xss": "HIGH",
            "secret_leak": "CRITICAL",
            "path_traversal": "HIGH",
            "prompt_injection": "MEDIUM",
        }
        return mapping.get(threat_type, "LOW")
    
    def _severity_value(self, sev: str) -> int:
        return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(sev, 1)
    
    def stats(self) -> Dict[str, Any]:
        return {
            "total_scans": self.allowed_count + self.blocked_count,
            "blocked": self.blocked_count,
            "allowed": self.allowed_count,
            "alerts": len(self.alerts),
        }
