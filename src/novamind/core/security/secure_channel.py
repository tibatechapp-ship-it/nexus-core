"""SecureChannel — قناة تواصل مؤمَّنة"""
from dataclasses import dataclass
from typing import Dict, Optional
import time
import json
import hmac
import hashlib
import secrets
import logging

from .injection_guard import InjectionGuard, ThreatDetection
from .key_manager import KeyManager

logger = logging.getLogger("security.secure_channel")


class SecurityViolation(Exception):
    pass


@dataclass
class SecureMessage:
    sender: str
    receiver: str
    payload: Dict
    nonce: str
    signature: str
    timestamp: float
    message_id: str = ""

    def to_dict(self) -> Dict:
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "payload": self.payload,
            "nonce": self.nonce,
            "signature": self.signature,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
        }


class SecureChannel:
    MAX_TIMESTAMP_SKEW = 60
    MAX_MESSAGES_PER_MIN = 100

    def __init__(self, key_manager: KeyManager, injection_guard: InjectionGuard):
        self.key_manager = key_manager
        self.injection_guard = injection_guard
        self.seen_nonces: Dict[str, float] = {}
        self.seen_ids: Dict[str, float] = {}
        self.rate_limits: Dict[str, list] = {}
        self.messages_sent = 0
        self.messages_received = 0
        self.messages_rejected = 0
        self.violations: list = []

    def send(self, sender: str, receiver: str, payload: Dict) -> SecureMessage:
        # 1. فحص الحقن
        payload_str = json.dumps(payload, ensure_ascii=False)
        is_safe, threat = self.injection_guard.is_safe(payload_str)
        if not is_safe:
            self._record_violation(sender, "injection_blocked", threat)
            raise SecurityViolation(f"Injection blocked: {threat.threat_type.value}")

        # 2. Rate limiting
        self._check_rate_limit(sender)

        # 3. مفتاح
        kp = self.key_manager.get_or_create(sender, receiver)

        # 4. Nonce + ID + Time
        nonce = secrets.token_hex(16)
        message_id = secrets.token_hex(8)
        timestamp = time.time()

        # 5. توقيع
        signature = self._sign(
            key=kp.shared_key,
            sender=sender, receiver=receiver,
            payload=payload, nonce=nonce,
            timestamp=timestamp, message_id=message_id,
        )

        msg = SecureMessage(
            sender=sender, receiver=receiver, payload=payload,
            nonce=nonce, signature=signature,
            timestamp=timestamp, message_id=message_id,
        )
        self.messages_sent += 1
        return msg

    def receive(self, msg: SecureMessage) -> Dict:
        self.messages_received += 1

        if msg.nonce in self.seen_nonces:
            self.messages_rejected += 1
            self._record_violation(msg.sender, "nonce_replay", None)
            raise SecurityViolation("Nonce already seen (replay attack)")

        if msg.message_id in self.seen_ids:
            self.messages_rejected += 1
            self._record_violation(msg.sender, "duplicate_id", None)
            raise SecurityViolation("Duplicate message ID")

        age = abs(time.time() - msg.timestamp)
        if age > self.MAX_TIMESTAMP_SKEW:
            self.messages_rejected += 1
            self._record_violation(msg.sender, "stale_message", None)
            raise SecurityViolation(f"Message too old: {age:.1f}s")

        payload_str = json.dumps(msg.payload, ensure_ascii=False)
        is_safe, threat = self.injection_guard.is_safe(payload_str)
        if not is_safe:
            self.messages_rejected += 1
            self._record_violation(msg.sender, "injection_in_receive", threat)
            raise SecurityViolation(f"Injection in payload: {threat.threat_type.value}")

        kp = self.key_manager.get_or_create(msg.sender, msg.receiver)
        expected = self._sign(
            key=kp.shared_key,
            sender=msg.sender, receiver=msg.receiver,
            payload=msg.payload, nonce=msg.nonce,
            timestamp=msg.timestamp, message_id=msg.message_id,
        )

        if not hmac.compare_digest(expected, msg.signature):
            self.messages_rejected += 1
            self._record_violation(msg.sender, "bad_signature", None)
            raise SecurityViolation("Invalid signature — message tampered!")

        self.seen_nonces[msg.nonce] = time.time()
        self.seen_ids[msg.message_id] = time.time()
        self._cleanup_seen()

        return msg.payload

    def _sign(self, key, sender, receiver, payload, nonce, timestamp, message_id) -> str:
        payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        canonical = f"{sender}|{receiver}|{nonce}|{timestamp:.6f}|{message_id}|{payload_str}"
        return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def _check_rate_limit(self, sender: str):
        now = time.time()
        window = 60
        if sender not in self.rate_limits:
            self.rate_limits[sender] = []
        self.rate_limits[sender] = [t for t in self.rate_limits[sender] if now - t < window]
        if len(self.rate_limits[sender]) >= self.MAX_MESSAGES_PER_MIN:
            self._record_violation(sender, "rate_limit_exceeded", None)
            raise SecurityViolation(f"Rate limit exceeded: {sender}")
        self.rate_limits[sender].append(now)

    def _cleanup_seen(self):
        cutoff = time.time() - 300
        self.seen_nonces = {k: v for k, v in self.seen_nonces.items() if v > cutoff}
        self.seen_ids = {k: v for k, v in self.seen_ids.items() if v > cutoff}

    def _record_violation(self, sender: str, vtype: str, threat: Optional[ThreatDetection]):
        v = {
            "sender": sender, "type": vtype,
            "threat": threat.threat_type.value if threat else None,
            "at": time.time(),
        }
        self.violations.append(v)
        logger.warning(f"🚨 Violation: {v}")

    def stats(self) -> Dict:
        return {
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "messages_rejected": self.messages_rejected,
            "rejection_rate": round(
                self.messages_rejected / max(1, self.messages_received), 3
            ),
            "violations_count": len(self.violations),
            "injection_guard": self.injection_guard.stats(),
            "key_manager": self.key_manager.stats(),
        }
