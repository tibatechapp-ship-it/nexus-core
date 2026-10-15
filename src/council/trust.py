"""Trust Boundary — لا نثق بأي رسالة بين الوكلاء."""
from __future__ import annotations
import hashlib
import hmac
import time
from dataclasses import dataclass, field


@dataclass
class SignedMessage:
    sender: str
    recipient: str
    content: str
    timestamp: float = field(default_factory=time.time)
    nonce: str = ""
    signature: str = ""
    provenance: list = field(default_factory=list)

    def sign(self, secret: bytes) -> None:
        payload = f"{self.sender}|{self.recipient}|{self.content}|{self.timestamp}|{self.nonce}"
        self.signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()

    def verify(self, secret: bytes) -> bool:
        payload = f"{self.sender}|{self.recipient}|{self.content}|{self.timestamp}|{self.nonce}"
        expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature, expected)


class TrustBoundary:
    def __init__(self, secret: bytes = None):
        self.secret = secret or b"council-shared-secret-change-me"
        self.message_log: list[SignedMessage] = []

    def send(self, sender, recipient, content, provenance=None):
        import secrets as _s
        msg = SignedMessage(
            sender=sender, recipient=recipient, content=content,
            nonce=_s.token_hex(8), provenance=provenance or [sender],
        )
        msg.sign(self.secret)
        self.message_log.append(msg)
        return msg

    def receive(self, msg):
        if not msg.verify(self.secret):
            return False, "توقيع غير صالح"
        if time.time() - msg.timestamp > 300:
            return False, "رسالة قديمة"
        for old in self.message_log[:-1]:
            if old.nonce == msg.nonce:
                return False, "nonce مكرر"
        return True, "موثوقة"
