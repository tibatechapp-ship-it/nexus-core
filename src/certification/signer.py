"""Certificate Signer — توقيع رقمي للشهادات.

يستخدم Ed25519 (cryptography) أو SHA256 كبديل.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

__all__ = ["Signer", "SignerError"]

KEYS_DIR = Path.home() / ".config" / "nexus" / "keys"
PRIVATE_KEY_FILE = KEYS_DIR / "signing.key"
PUBLIC_KEY_FILE = KEYS_DIR / "signing.pub"


class SignerError(RuntimeError):
    """فشل التوقيع."""


class Signer:
    """يوقّع الشهادات."""
    
    def __init__(self, use_ed25519: bool = True) -> None:
        self.keys_dir = KEYS_DIR
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        self.use_ed25519 = use_ed25519
        self._private_key = None
        self._public_key = None
        self._load_or_create_keys()
    
    def _load_or_create_keys(self) -> None:
        """يحمّل أو ينشئ مفاتيح التوقيع."""
        if self.use_ed25519:
            try:
                self._init_ed25519()
                return
            except ImportError:
                print("⚠️ cryptography غير مثبت — استخدام SHA256")
                self.use_ed25519 = False
        
        self._init_sha256()
    
    def _init_ed25519(self) -> None:
        """Ed25519 keys."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives import serialization
        
        if PRIVATE_KEY_FILE.exists():
            with open(PRIVATE_KEY_FILE, "rb") as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
        else:
            self._private_key = Ed25519PrivateKey.generate()
            with open(PRIVATE_KEY_FILE, "wb") as f:
                f.write(self._private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                ))
            os.chmod(PRIVATE_KEY_FILE, 0o600)
        
        self._public_key = self._private_key.public_key()
        
        # احفظ المفتاح العام
        with open(PUBLIC_KEY_FILE, "wb") as f:
            f.write(self._public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
    
    def _init_sha256(self) -> None:
        """SHA256 fallback (less secure)."""
        if PRIVATE_KEY_FILE.exists():
            self._private_key = PRIVATE_KEY_FILE.read_bytes()
        else:
            self._private_key = os.urandom(32)
            PRIVATE_KEY_FILE.write_bytes(self._private_key)
            os.chmod(PRIVATE_KEY_FILE, 0o600)
        
        self._public_key = hashlib.sha256(self._private_key).digest()
        PUBLIC_KEY_FILE.write_bytes(self._public_key)
    
    def _canonical(self, data: dict[str, Any]) -> bytes:
        """JSON canonical form."""
        return json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    
    def sign(self, data: dict[str, Any]) -> str:
        """يوقّع بيانات ويعيد التوقيع base64."""
        payload = self._canonical(data)
        
        if self.use_ed25519:
            sig_bytes = self._private_key.sign(payload)
        else:
            sig_bytes = hashlib.sha256(payload + self._private_key).digest()
        
        return base64.b64encode(sig_bytes).decode("ascii")
    
    def public_key_b64(self) -> str:
        """يعيد المفتاح العام base64."""
        if self.use_ed25519:
            from cryptography.hazmat.primitives import serialization
            pub_bytes = self._public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        else:
            pub_bytes = self._public_key
        
        return base64.b64encode(pub_bytes).decode("ascii")
    
    def verify(self, data: dict[str, Any], signature_b64: str) -> bool:
        """يتحقق من التوقيع."""
        try:
            payload = self._canonical(data)
            sig_bytes = base64.b64decode(signature_b64)
            
            if self.use_ed25519:
                self._public_key.verify(sig_bytes, payload)
                return True
            else:
                expected = hashlib.sha256(payload + self._private_key).digest()
                return sig_bytes == expected
        except Exception:
            return False
