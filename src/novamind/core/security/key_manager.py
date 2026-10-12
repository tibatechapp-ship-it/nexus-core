"""KeyManager — إدارة المفاتيح"""
from dataclasses import dataclass
from typing import Dict
from pathlib import Path
import os
import time
import hashlib
import secrets
import logging

logger = logging.getLogger("security.key_manager")


@dataclass
class KeyPair:
    agent_a: str
    agent_b: str
    shared_key: bytes
    created_at: float
    expires_at: float
    rotation_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class KeyManager:
    KEY_SIZE = 32
    KEY_TTL = 3600

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir) / ".nova" / "keys"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.keys: Dict[str, KeyPair] = {}
        self.master_key = self._load_or_create_master_key()

    def _load_or_create_master_key(self) -> bytes:
        f = self.base_dir / ".master"
        if f.exists():
            return f.read_bytes()
        key = secrets.token_bytes(self.KEY_SIZE)
        f.write_bytes(key)
        try:
            os.chmod(f, 0o600)
        except Exception:
            pass
        logger.info("Master key generated")
        return key

    def _pair_id(self, a: str, b: str) -> str:
        s = sorted([a, b])
        return hashlib.sha256(f"{s[0]}::{s[1]}".encode()).hexdigest()[:16]

    def get_or_create(self, agent_a: str, agent_b: str) -> KeyPair:
        pid = self._pair_id(agent_a, agent_b)
        if pid in self.keys and not self.keys[pid].is_expired:
            return self.keys[pid]
        shared = secrets.token_bytes(self.KEY_SIZE)
        kp = KeyPair(
            agent_a=agent_a, agent_b=agent_b,
            shared_key=shared,
            created_at=time.time(),
            expires_at=time.time() + self.KEY_TTL,
        )
        self.keys[pid] = kp
        return kp

    def rotate(self, agent_a: str, agent_b: str) -> KeyPair:
        pid = self._pair_id(agent_a, agent_b)
        old = self.keys.get(pid)
        shared = secrets.token_bytes(self.KEY_SIZE)
        kp = KeyPair(
            agent_a=agent_a, agent_b=agent_b,
            shared_key=shared,
            created_at=time.time(),
            expires_at=time.time() + self.KEY_TTL,
            rotation_count=(old.rotation_count + 1) if old else 1,
        )
        self.keys[pid] = kp
        return kp

    def revoke(self, agent_a: str, agent_b: str):
        pid = self._pair_id(agent_a, agent_b)
        self.keys.pop(pid, None)

    def cleanup_expired(self) -> int:
        expired = [pid for pid, kp in self.keys.items() if kp.is_expired]
        for pid in expired:
            del self.keys[pid]
        return len(expired)

    def stats(self) -> Dict:
        return {
            "active_keys": len(self.keys),
            "total_rotations": sum(kp.rotation_count for kp in self.keys.values()),
        }
