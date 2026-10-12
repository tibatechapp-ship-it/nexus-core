"""Rate Limiter — حماية من تجاوز حدود المزوّدين.

يتتبع tokens لكل مزوّد في نافذة زمنية، ويؤخر الطلبات عند الحاجة.

الحدود المعروفة:
- Groq Free: 8000 TPM (tokens per minute)
- OpenRouter Free: 200 req/hour

Usage:
    limiter = RateLimiter()
    await limiter.wait_if_needed("groq", tokens_estimate=2000)
    # ... نفذ الـ LLM call
    limiter.record("groq", tokens_used=1500)
"""
from __future__ import annotations
from collections import defaultdict, deque
from typing import Dict, Tuple
from datetime import datetime, timezone
import asyncio
import time


class RateLimiter:
    """متتبع بسيط للحدود."""

    # الحدود (provider → max_tokens_per_minute)
    LIMITS: Dict[str, int] = {
        "groq": 8000,
        "openrouter": 20000,
        "gemini": 60000,
        "zai": 10000,
        "default": 5000,
    }

    # نافذة زمنية (ثوان)
    WINDOW = 60

    def __init__(self):
        # (provider, timestamp) → tokens
        self._history: Dict[str, deque] = defaultdict(lambda: deque())
        self._lock = asyncio.Lock()

    def _provider_key(self, provider: str) -> str:
        """يرجع المفتاح الطبيعي (groq-01 → groq)."""
        for key in self.LIMITS:
            if provider.lower().startswith(key):
                return key
        return "default"

    def _get_limit(self, provider: str) -> int:
        return self.LIMITS.get(self._provider_key(provider), self.LIMITS["default"])

    def _prune(self, provider: str):
        """يحذف السجلات القديمة (أقدم من WINDOW)."""
        key = self._provider_key(provider)
        cutoff = time.time() - self.WINDOW
        dq = self._history[key]
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def tokens_in_window(self, provider: str) -> int:
        """مجموع tokens في النافذة الحالية."""
        self._prune(provider)
        key = self._provider_key(provider)
        return sum(t for _, t in self._history[key])

    async def wait_if_needed(
        self,
        provider: str,
        tokens_estimate: int = 2000,
        max_wait: float = 60.0,
    ) -> float:
        """ينتظر إن كانت الحدود قاربت على الامتلاء.

        Returns:
            عدد الثواني التي انتظرها
        """
        async with self._lock:
            key = self._provider_key(provider)
            limit = self._get_limit(provider)
            current = self.tokens_in_window(provider)
            needed = current + tokens_estimate

            if needed <= limit:
                return 0.0  # لا انتظار

            # احسب كم يجب الانتظار
            self._prune(provider)
            dq = self._history[key]
            if not dq:
                return 0.0

            # أقدم سجل
            oldest_ts = dq[0][0]
            wait_time = self.WINDOW - (time.time() - oldest_ts)
            wait_time = max(0, min(wait_time, max_wait))

        if wait_time > 0:
            await asyncio.sleep(wait_time)
        return wait_time

    def record(self, provider: str, tokens_used: int):
        """سجّل استخدام tokens."""
        key = self._provider_key(provider)
        self._history[key].append((time.time(), tokens_used))

    def status(self) -> Dict[str, Dict]:
        """ملخص الحالة."""
        out = {}
        for p in self.LIMITS:
            used = self.tokens_in_window(p)
            limit = self.LIMITS[p]
            out[p] = {
                "used": used,
                "limit": limit,
                "pct": round(100 * used / limit, 1) if limit else 0,
            }
        return out

    def reset(self):
        """محي السجل."""
        self._history.clear()


# singleton
_LIMITER: RateLimiter = None


def get_limiter() -> RateLimiter:
    """يرجع الـ singleton."""
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RateLimiter()
    return _LIMITER
