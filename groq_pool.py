#!/usr/bin/env python3
"""Groq Key Pool — rotation + cooldown + stats"""
import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("groq_pool")

POOL_STATE = Path("/public/memory/groq_pool.json")
MAX_KEYS = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class GroqKeyPool:
    """Manages Groq API keys with rotation + cooldown."""

    def __init__(self, keys: Optional[List[str]] = None):
        self.keys = keys or self._load_keys()
        self.state = self._load_state()
        self._ensure_state()

    def _load_keys(self) -> List[str]:
        keys = []
        for i in range(1, MAX_KEYS + 1):
            k = os.environ.get(f"GROQ_API_KEY_{i}", "").strip()
            if k and k.startswith("gsk_") and len(k) > 30:
                keys.append(k)
        # Fallback: old
        old = os.environ.get("GROQ_API_KEY", "").strip()
        if old and old.startswith("gsk_") and old not in keys:
            keys.append(old)
        return keys

    def _load_state(self) -> Dict:
        if not POOL_STATE.exists():
            return {}
        try:
            return json.loads(POOL_STATE.read_text())
        except Exception:
            return {}

    def _ensure_state(self):
        for i, key in enumerate(self.keys):
            kid = f"key-{i+1:02d}"
            if kid not in self.state:
                self.state[kid] = {
                    "index": i,
                    "key_prefix": key[:12] + "...",
                    "uses": 0,
                    "errors": 0,
                    "cooldown_until": 0,
                    "last_used": 0,
                    "last_error": "",
                }
        self._save_state()

    def _save_state(self):
        POOL_STATE.parent.mkdir(parents=True, exist_ok=True)
        POOL_STATE.write_text(json.dumps(self.state, indent=2))

    def get_next_key(self) -> Optional[Dict]:
        now = time.time()
        available = []
        for kid, info in self.state.items():
            if info["cooldown_until"] > now:
                continue
            available.append((info["last_used"], kid, info))

        if not available:
            logger.warning("All Groq keys in cooldown!")
            return None

        available.sort(key=lambda x: x[0])
        _, kid, info = available[0]
        idx = info["index"]

        return {
            "id": kid,
            "key": self.keys[idx],
            "prefix": info["key_prefix"],
            "uses": info["uses"],
        }

    def report_success(self, kid: str):
        if kid in self.state:
            self.state[kid]["uses"] += 1
            self.state[kid]["last_used"] = time.time()
            self._save_state()

    def report_error(self, kid: str, error: str, cooldown_sec: int = 60):
        if kid in self.state:
            info = self.state[kid]
            info["errors"] += 1
            info["last_error"] = error[:200]
            info["cooldown_until"] = time.time() + cooldown_sec
            self._save_state()

    def report_rate_limit(self, kid: str):
        self.report_error(kid, "rate limit", cooldown_sec=300)

    def stats(self) -> Dict:
        now = time.time()
        available = sum(
            1 for info in self.state.values()
            if info["cooldown_until"] <= now
        )
        return {
            "total_keys": len(self.keys),
            "available": available,
            "in_cooldown": len(self.keys) - available,
            "keys": [
                {
                    "id": kid,
                    "uses": info["uses"],
                    "errors": info["errors"],
                    "available": info["cooldown_until"] <= now,
                    "cooldown_remaining": max(0, int(info["cooldown_until"] - now)),
                }
                for kid, info in sorted(self.state.items())
            ],
        }

    def reset_cooldowns(self):
        for info in self.state.values():
            info["cooldown_until"] = 0
        self._save_state()
        logger.info("All cooldowns reset")


_pool = None


def get_pool() -> GroqKeyPool:
    global _pool
    if _pool is None:
        _pool = GroqKeyPool()
    return _pool


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        from dotenv import load_dotenv
        load_dotenv("/public/.env")
    except ImportError:
        pass

    pool = GroqKeyPool()

    print()
    print("═" * 60)
    print(f"  🔑 Groq Key Pool")
    print("═" * 60)
    print()
    print(f"  Loaded: {len(pool.keys)} keys")
    print()

    if not pool.keys:
        print("❌ No keys found!")
        sys.exit(1)

    for i, k in enumerate(pool.keys, 1):
        print(f"  {i:2d}. {k[:16]}... (len: {len(k)})")

    print()
    print("═══ Pool Stats ═══")
    stats = pool.stats()
    print(f"  Total:      {stats['total_keys']}")
    print(f"  Available:  {stats['available']}")
    print(f"  Cooldown:   {stats['in_cooldown']}")
    print()
