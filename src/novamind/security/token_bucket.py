"""TokenBucketLimiter — O(1) rate limiter for high load."""
import time
import asyncio
import logging
from typing import Optional

log = logging.getLogger("TokenBucketLimiter")


class TokenBucketLimiter:
    """Token Bucket — مناسب للأحمال العالية (O(1))."""

    def __init__(self, name, rate=60, capacity=120):
        """
        Args:
            name: اسم الlimiter
            rate: عدد الرموز المُجدَّدة في الثانية
            capacity: السعة القصوى للـ bucket
        """
        self.name = name
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = asyncio.Lock()
        self.total_allowed = 0
        self.total_denied = 0

    def _refill(self):
        """يعيد ملء الرموز بناءً على الوقت المنقضي."""
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now

    async def acquire(self, key="default", cost=1):
        """يطلب رمز/رموز."""
        async with self.lock:
            self._refill()

            if self.tokens >= cost:
                self.tokens -= cost
                self.total_allowed += 1
                return {
                    "allowed": True,
                    "remaining": int(self.tokens),
                    "capacity": self.capacity,
                    "rate": self.rate,
                }

            self.total_denied += 1
            wait_time = (cost - self.tokens) / self.rate
            return {
                "allowed": False,
                "remaining": 0,
                "retry_after": round(wait_time, 3),
                "error": "rate_limit_exceeded",
            }

    def stats(self):
        self._refill()
        return {
            "name": self.name,
            "type": "token_bucket",
            "rate": self.rate,
            "capacity": self.capacity,
            "tokens_available": int(self.tokens),
            "total_allowed": self.total_allowed,
            "total_denied": self.total_denied,
        }


_buckets = {}


def get_token_bucket(name, **kwargs) -> TokenBucketLimiter:
    """يرجع bucket بالاسم."""
    if name not in _buckets:
        _buckets[name] = TokenBucketLimiter(name, **kwargs)
    return _buckets[name]
