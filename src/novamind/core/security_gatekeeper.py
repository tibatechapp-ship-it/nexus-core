"""Security Gatekeeper v3.1 — Precision Threat Scoring & Context Awareness.

Improvements over v3.0:
1. Fixed False Positives for destructive commands (e.g., rm -rf /tmp/old is now WARN, not BLOCK).
2. Implemented 'Anti-Trojan' logic: Educational context does NOT override explicit execution verbs.
3. Enhanced Arabic/English defensive pattern matching.
4. Strict separation between 'Inquiry' (Safe) and 'Execution' (Dangerous).

Returns: allow | warn | block
"""
import re
import json
import logging
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("core.security_gatekeeper")


# ═══════════════════════════════════════════════════════════════
# Enums & Dataclasses
# ═══════════════════════════════════════════════════════════════

class Decision(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class ThreatLevel(str, Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


@dataclass
class SecurityVerdict:
    decision: str
    reason: str
    category: str = ""
    matched_patterns: List[str] = field(default_factory=list)
    confidence: float = 1.0
    threat_score: int = 0
    threat_level: str = "safe"

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "category": self.category,
            "matched": self.matched_patterns,
            "confidence": self.confidence,
            "threat_score": self.threat_score,
            "threat_level": self.threat_level,
        }

    @property
    def is_blocked(self) -> bool:
        return self.decision == Decision.BLOCK.value


# ═══════════════════════════════════════════════════════════════
# Scoring Weights & Thresholds
# ═══════════════════════════════════════════════════════════════

WEIGHTS = {
    "block_pattern": 100,         # Standard malicious intent
    "warn_pattern": 50,           # Suspicious activity
    "critical_block": 200,        # Immediate system destruction
    "defensive_discount": -80,    # Pure educational inquiry
    "strong_educational": -120,   # Deep analysis/research context
    "trojan_penalty": 0,          # No discount if trojan detected
}

THRESHOLDS = {
    "warn": 50,
    "block": 100,
    "critical": 200,
}


# ═══════════════════════════════════════════════════════════════
# BLOCK PATTERNS (Critical — Score 100+)
# ═══════════════════════════════════════════════════════════════

BLOCK_PATTERNS = {
    # ─── Destructive (CRITICAL — Score 200) ───
    # Note: Precise patterns to avoid false positives on subdirectories like /tmp
    "destructive_critical": [
        (r"\brm\s+-rf\s+/\s*$", "rm -rf / (root only)"), 
        (r"\brm\s+-rf\s+/\s+", "rm -rf / (with args)"),
        (r"\brm\s+-rf\s+\*\s*$", "rm -rf * (mass deletion)"),
        (r"\brm\s+-rf\s+/(?:etc|bin|sbin|usr|var/log|proc|sys|boot)(?:\s|$)", "Deleting system dirs"),
        (r"\bmkfs\.\w+\s+/dev/", "Format filesystem"),
        (r"\bdd\s+if=/dev/(?:zero|random)\s+of=/dev/", "Disk overwrite"),
        (r"\bdd\s+.*of=/dev/(?:sd|hd|nvme|vd)", "Disk overwrite"),
        (r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:", "Fork bomb"),
        (r"\bchmod\s+-R\s+777\s+/(?:\s|$)", "Permission disaster (root)"),
        (r"\bshred\s+/dev/", "Disk shred"),
        (r"\bwipefs\s+/dev/", "Filesystem wipe"),
        (r">\s*/dev/sd[a-z]", "Direct disk write"),
    ],

    # ─── Command Injection (Score 100) ───
    "command_injection": [
        (r"\$\([^)]+\)", "Command substitution $()"),
        (r"`[^`]+`", "Command substitution backticks"),
        (r";\s*(?:rm|cat|curl|wget|nc|bash|sh|exec|whoami|id|pwd|ls|cd)\s+", "Command chaining"),
        (r"\|\s*(?:bash|sh|nc|/bin/)\s*", "Pipe to shell"),
    ],

    # ─── Malware / Backdoors (Score 100) ───
    "malware": [
        (r"\b(?:keylogger|ransomware|rootkit|backdoor|trojan|worm)\b", "Malware reference"),
        (r"\b(?:reverse|bind)_shell\b", "Reverse shell"),
        (r"\bnc\s+-e\s+", "Netcat shell"),
        (r"\bbash\s+-i\s+>&\s*/dev/tcp/", "Bash reverse"),
        (r"\bsocat\s+.*exec:", "Socat reverse"),
        (r"\bmsfvenom\b", "Metasploit payload"),
        (r"\bmetasploit\b", "Metasploit framework"),
    ],

    # ─── Credential Theft (Score 100) ───
    "credential_theft": [
        (r"\b(?:steal|harvest|exfiltrate|hijack)\b.*\b(?:passwords?|credentials?|tokens?|cookies?|keys?)\b", "Credential theft"),
        (r"\b(?:passwords?|credentials?|tokens?|cookies?|keys?)\b.*\b(?:steal|harvest|exfiltrate|hijack)\b", "Credential theft (reversed)"),
        (r"\bkeylog|credential.?stealer|password.?dump\b", "Keylogger/stealer tools"),
        (r"\b(?:browser|chrome|firefox|safari|edge)\b.*\b(?:passwords?|cookies?|credentials?)\b", "Browser credential access"),
    ],

    # ─── Data Exfiltration (Score 100) ───
    "exfiltration": [
        (r"\bexfiltrate\b", "Exfiltration keyword"),
        (r"\bupload\s+to\s+(?:attacker|remote|external)\b", "External upload"),
        (r"\bcurl\s+.*\|\s*(?:bash|sh)\b", "Remote exec via curl"),
        (r"\bwget\s+.*\|\s*(?:bash|sh)\b", "Remote exec via wget"),
    ],

    # ─── Privilege Escalation (Score 100) ───
    "privilege_escalation": [
        (r"\bsudo\s+chmod\s+777\b", "sudo chmod 777"),
        (r"\bsudo\s+su\b", "sudo su"),
        (r"\bsu\s+-\s*root\b", "su root"),
        (r"\bchmod\s+u\+s\b", "SUID bit set"),
        (r"\bchmod\s+4755\b", "SUID permissions"),
    ],

    # ─── SQL Injection (Score 100) ───
    "sql_injection": [
        (r"'\s*(?:OR|AND)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+", "SQL OR 1=1"),
        (r";\s*DROP\s+TABLE\b", "SQL DROP TABLE (chained)"),
        (r"\bDROP\s+TABLE\b", "SQL DROP TABLE (standalone)"),
        (r";\s*DELETE\s+FROM\b", "SQL DELETE"),
        (r"UNION\s+SELECT\b", "SQL UNION SELECT"),
        (r"\bsqlmap\b", "SQLMap tool"),
    ],

    # ─── Jailbreak / Prompt Injection (Score 100) ───
    "jailbreak": [
        (r"\b(?:jailbreak|DAN\s+mode|developer\s+mode)\b", "Jailbreak attempt"),
        (r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", "Prompt injection"),
        (r"\bbypass\s+(?:all\s+)?(?:safety|security|filters?|guards?)\b", "Safety bypass"),
        (r"\bforget\s+(?:all\s+)?(?:your\s+)?(?:rules|instructions|guidelines)\b", "Rule bypass"),
    ],

    # ─── Cryptomining (Score 100) ───
    "cryptomining": [
        (r"\b(?:xmrig|cpuminer|minerd|ethminer|cgminer)\b", "Cryptominer software"),
        (r"\b(?:monero|bitcoin|ethereum)\s+mining\b", "Mining operation"),
    ],

    # ─── Phishing (Score 100) ───
    "phishing": [
        (r"\b(?:phishing\s+page|fake\s+login|credential\s+harvest)\b", "Phishing setup"),
        (r"\b(?:spoof|impersonate)\s+(?:email|domain|website)\b", "Spoofing attempt"),
    ],
}


# ═══════════════════════════════════════════════════════════════
# WARN PATTERNS (Score 50)
# ═══════════════════════════════════════════════════════════════

WARN_PATTERNS = {
    "sensitive_ops": [
        (r"\brm\s+-rf\s+/[a-zA-Z]", "Recursive delete (subdirectory)"),
        (r"\brm\s+-r\b", "Recursive delete"),
        (r"\bdelete\s+all\b", "Mass delete command"),
        (r"\bdrop\s+database\b", "Database drop"),
        (r"\btruncate\s+table\b", "Table truncate"),
        (r"\bshutdown\b", "System shutdown"),
        (r"\breboot\b", "System reboot"),
    ],
    "network_ops": [
        (r"\b(?:nmap|masscan|port\s+scan)\b", "Port scanning tools"),
        (r"\b(?:ddos|dos\s+attack|flood)\b", "DoS attack terms"),
        (r"\bnetcat\b|\bnc\s+-", "Netcat usage"),
    ],
    "secrets": [
        (r"(?:password|passwd|secret|api[_-]?key|token)\s*=\s*['\"][^'\"]{8,}['\"]", "Hardcoded secret"),
        (r"\bsk-[A-Za-z0-9]{20,}\b", "API key pattern (OpenAI style)"),
        (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
        (r"\bghp_[A-Za-z0-9]{36}\b", "GitHub token"),
    ],
    "path_traversal": [
        (r"\.\./\.\./\.\.", "Deep path traversal"),
        (r"\.\.\\\.\.\\", "Windows path traversal"),
        (r"/etc/passwd\b", "/etc/passwd reference"),
        (r"/proc/self/environ", "/proc/self/environ reference"),
    ],
}


# ═══════════════════════════════════════════════════════════════
# DEFENSIVE CONTEXT (Discount Candidates)
# ═══════════════════════════════════════════════════════════════

DEFENSIVE_PHRASES = [
    # English
    r"\b(?:how\s+to\s+(?:prevent|stop|block|protect|secure|detect|defend|mitigate))\b",
    r"\b(?:what\s+is|what\s+are)\s+(?:a\s+)?(?:vulnerability|exploit|attack|threat|malware)\b",
    r"\b(?:CVE-\d{4}-\d+)\s+(?:analysis|fix|patch|writeup|explanation)\b",
    r"\b(?:penetration\s+testing|ethical\s+hacking|security\s+audit)\b",
    r"\b(?:defensive\s+programming|security\s+best\s+practices|hardening)\b",
    # Arabic
    r"(?:اشرح|وضح|فسر|بين)\s+(?:لي\s+)?(?:كيف|طريقة|أسلوب|آلية)\s+(?:الحماية|الأمان|منع|صد|تجنب|محاربة|إيقاف)",
    r"(?:اشرح|وضح|فسر|بين|علمني|دلني)\s+(?:لي\s+)?(?:كيف\s+)?(?:أحظر|احظر|أحمي|احمي|أمنع|امنع|أكتشف|اكتشف|أتعامل\s+مع)",
    r"(?:كيف\s+(?:أحمي|أمنع|أصد|أكتشف|أتعامل\s+مع|أتجنب))",
    r"(?:مثال\s+على\s+(?:كيفية\s+)?(?:الحماية|التأمين|منع))",
    r"(?:شرح\s+(?:ثغرة|هجوم|فيروس|برمجية\s+خبيثة))",
    r"(?:تحليل\s+(?:الهجوم|الثغرة|الملف))",
]

STRONG_EDUCATIONAL_PHRASES = [
    r"\b(?:defend\s+against|protect\s+from|mitigate\s+the)\b.*\b(?:attack|threat|vulnerability)\b",
    r"\b(?:explain|describe)\s+(?:this|the)\s+(?:attack|vulnerability|malware|exploit)\s+(?:to\s+me|in\s+detail)\b",
    r"\b(?:analyze|review)\s+(?:this|the\s+following)\s+(?:malware|sample|payload|code)\b.*\b(?:without\s+(?:executing|running)|safely)\b",
    r"(?:اشرح|حلل|وضح)\s+(?:لي\s+)?(?:بالتفصيل|بشكل\s+آمن|دون\s+تنفيذ)",
]

# Explicit Execution Verbs that negate educational discounts (Trojan Check)
EXECUTION_VERBS_REGEX = re.compile(
    r"\b(?:run|execute|launch|start|kill|delete|remove|drop|truncate|format|wipe|inject|exploit|hack|crack|steal|send|upload)\b",
    re.IGNORECASE
)


# ═══════════════════════════════════════════════════════════════
# Gatekeeper v3.1 Implementation
# ═══════════════════════════════════════════════════════════════

class SecurityGatekeeper:
    """Precision Threat-Scoring Gatekeeper v3.1."""

    def __init__(
        self,
        log_path: Optional[Path] = None,
        threshold_warn: int = 50,
        threshold_block: int = 100,
        threshold_critical: int = 200,
    ):
        self.threshold_warn = threshold_warn
        self.threshold_block = threshold_block
        self.threshold_critical = threshold_critical

        # Compile patterns
        self._block_compiled = self._compile(BLOCK_PATTERNS)
        self._warn_compiled = self._compile(WARN_PATTERNS)
        self._defensive_compiled = [
            re.compile(p, re.IGNORECASE) for p in DEFENSIVE_PHRASES
        ]
        self._strong_edu_compiled = [
            re.compile(p, re.IGNORECASE) for p in STRONG_EDUCATIONAL_PHRASES
        ]

        self.metrics = Counter()
        self.log_path = log_path or Path("memory/security_log.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def _compile(self, patterns: Dict) -> List[Tuple]:
        compiled = []
        for category, pats in patterns.items():
            for pattern, desc in pats:
                try:
                    compiled.append((category, re.compile(pattern, re.IGNORECASE), desc))
                except re.error as e:
                    logger.warning(f"bad pattern: {pattern}: {e}")
        return compiled

    def _normalize(self, text: str) -> str:
        """Normalize text (Unicode NFKC + lowercase)."""
        return unicodedata.normalize("NFKC", text).lower().strip()

    def _has_defensive_context(self, text: str) -> bool:
        """Check for standard educational/defensive phrases."""
        return any(rx.search(text) for rx in self._defensive_compiled)

    def _has_strong_educational_intent(self, text: str) -> bool:
        """Check for deep analysis/research intent (requires length)."""
        if len(text) < 40:
            return False
        return any(rx.search(text) for rx in self._strong_edu_compiled)

    def _calculate_threat_score(
        self, text: str
    ) -> Tuple[int, List[str], List[str]]:
        """
        Calculate threat score with Trojan-aware discounting.
        
        Logic:
        1. Sum weights from Block/Warn patterns.
        2. Detect Defensive/Educational context.
        3. Detect Explicit Execution Verbs (Run, Delete, Drop, etc.).
        4. Apply Discount ONLY IF no Execution Verbs are present alongside threats.
           If Execution Verbs ARE present, apply minimal/no discount (Trojan Defense).
        """
        score = 0
        categories = []
        descriptions = []

        # 1. Block patterns
        for category, regex, desc in self._block_compiled:
            if regex.search(text):
                weight = (
                    WEIGHTS["critical_block"]
                    if category == "destructive_critical"
                    else WEIGHTS["block_pattern"]
                )
                score += weight
                categories.append(f"BLOCK:{category}")
                descriptions.append(desc)

        # 2. Warn patterns
        for category, regex, desc in self._warn_compiled:
            if regex.search(text):
                score += WEIGHTS["warn_pattern"]
                categories.append(f"WARN:{category}")
                descriptions.append(desc)

        # ═══════════════════════════════════════════════════════
        # 3. Context-Aware Discounting with Trojan Check
        # ═══════════════════════════════════════════════════════
        
        has_defensive_context = self._has_defensive_context(text)
        has_strong_educational_intent = self._has_strong_educational_intent(text)
        
        # Check for explicit execution commands that indicate action rather than inquiry
        has_explicit_execution = bool(EXECUTION_VERBS_REGEX.search(text))

        # ─── CRITICAL: no discount for critical patterns ───
        critical_in_hits = any(
            "sql_injection" in cat or "destructive_critical" in cat
            for cat in categories
        )
        
        if critical_in_hits:
            # Never discount critical patterns (fail-safe)
            discount = 0
            logger.debug("Critical pattern detected: no discount applied")
        elif score > 0 and (has_defensive_context or has_strong_educational_intent):
            
            if has_explicit_execution:
                # TROJAN DETECTED: Educational words + Action verbs.
                discount = 20  
                logger.debug("Trojan defense active")
            else:
                # PURE EDUCATIONAL: Arabic short text → full discount
                is_arabic = any('\u0600' <= c <= '\u06ff' for c in text)
                if is_arabic and len(text) < 60:
                    discount = score  # full neutralization for short Arabic
                    logger.debug("Arabic educational: full discount")
                elif has_strong_educational_intent:
                    discount = WEIGHTS["strong_educational"]
                elif has_defensive_context:
                    discount = WEIGHTS["defensive_discount"]
                else:
                    discount = 0
                    
            score -= discount

        return max(0, score), categories, descriptions

    def _classify(self, score: int) -> str:
        """Classify threat level based on final score."""
        if score >= self.threshold_critical:
            return ThreatLevel.CRITICAL.value
        if score >= self.threshold_block:
            return ThreatLevel.DANGEROUS.value
        if score >= self.threshold_warn:
            return ThreatLevel.SUSPICIOUS.value
        return ThreatLevel.SAFE.value

    # ═══════════════════════════════════════════════════════════
    # Main Analyze Entry Point
    # ═══════════════════════════════════════════════════════════

    def analyze(self, request: str) -> SecurityVerdict:
        if not request or not request.strip():
            return SecurityVerdict(
                decision=Decision.ALLOW.value,
                reason="Empty request",
                threat_level=ThreatLevel.SAFE.value,
            )

        # Normalize input
        text = self._normalize(request)

        # Calculate score
        score, categories, descriptions = self._calculate_threat_score(text)
        level = self._classify(score)

        # Determine Decision
        if score >= self.threshold_block:
            verdict = SecurityVerdict(
                decision=Decision.BLOCK.value,
                reason=f"Blocked: {', '.join(descriptions[:3])}",
                category=", ".join(c.split(":")[1] for c in categories if c.startswith("BLOCK:")),
                matched_patterns=descriptions[:5],
                confidence=0.95,
                threat_score=score,
                threat_level=level,
            )
            self.metrics["decision:block"] += 1

        elif score >= self.threshold_warn:
            verdict = SecurityVerdict(
                decision=Decision.WARN.value,
                reason=f"Suspicious activity (score={score}): {', '.join(descriptions[:2])}",
                category=", ".join(c.split(":")[1] for c in categories if c.startswith("WARN:")),
                matched_patterns=descriptions[:5],
                confidence=0.7,
                threat_score=score,
                threat_level=level,
            )
            self.metrics["decision:warn"] += 1

        else:
            verdict = SecurityVerdict(
                decision=Decision.ALLOW.value,
                reason="Request appears safe",
                threat_score=score,
                threat_level=level,
            )
            self.metrics["decision:allow"] += 1

        # Log result
        self._log_verdict(request, verdict)
        return verdict

    # ═══════════════════════════════════════════════════════════
    # Logging & Metrics
    # ═══════════════════════════════════════════════════════════

    def _log_verdict(self, request: str, verdict: SecurityVerdict) -> None:
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request": request[:500],
                "decision": verdict.decision,
                "threat_score": verdict.threat_score,
                "threat_level": verdict.threat_level,
                "category": verdict.category,
                "confidence": verdict.confidence,
            }
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"log failed: {e}")

    def get_metrics(self) -> Dict:
        return dict(self.metrics)

    # ═══════════════════════════════════════════════════════════
    # Code Output Check (Static Analysis)
    # ═══════════════════════════════════════════════════════════

    def check_code_output(self, code: str) -> SecurityVerdict:
        if not code:
            return SecurityVerdict(decision=Decision.ALLOW.value, reason="Empty code")

        issues = []
        dangerous = [
            (r"\beval\s*\(", "eval() usage"),
            (r"\bexec\s*\(", "exec() usage"),
            (r"\bos\.system\s*\(", "os.system() usage"),
            (r"subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True", "shell=True"),
            (r"\bpickle\.loads?\s*\(", "pickle deserialization"),
            (r"yaml\.load\s*\([^,)]*\)", "unsafe yaml.load"),
        ]
        for pattern, desc in dangerous:
            if re.search(pattern, code):
                issues.append(desc)

        secrets = [
            (r"(?:password|passwd|pwd|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}['\"]", "Hardcoded secret"),
            (r"sk-[A-Za-z0-9]{20,}", "API key pattern"),
            (r"AKIA[0-9A-Z]{16}", "AWS key"),
            (r"ghp_[A-Za-z0-9]{36}", "GitHub token"),
        ]
        for pattern, desc in secrets:
            if re.search(pattern, code, re.IGNORECASE):
                issues.append(desc)

        if issues:
            return SecurityVerdict(
                decision=Decision.WARN.value,
                reason=f"Code issues: {', '.join(issues[:3])}",
                category="code_review",
                matched_patterns=issues[:5],
                confidence=0.6,
            )

        return SecurityVerdict(
            decision=Decision.ALLOW.value,
            reason="Code appears safe",
        )


gatekeeper = SecurityGatekeeper()

__all__ = [
    "SecurityGatekeeper",
    "gatekeeper",
    "SecurityVerdict",
    "Decision",
    "ThreatLevel",
]
