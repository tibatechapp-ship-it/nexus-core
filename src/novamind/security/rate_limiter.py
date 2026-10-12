"""RateLimiter — Sliding Window."""
import time
import logging
from collections import defaultdict, deque

log = logging.getLogger("RateLimiter")


class RateLimitError(Exception):
    pass


class RateLimiter:
    def __init__(self, name, max_requests=60, window_seconds=60, burst=0):
        self.name = name
        self.max_requests = max_requests
        self.window = window_seconds
        self.burst = burst
        self.buckets = defaultdict(deque)
        self.total_allowed = 0
        self.total_denied = 0

    def _prune(self, key):
        cutoff = time.time() - self.window
        bucket = self.buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def acquire(self, key="default"):
        self._prune(key)
        bucket = self.buckets[key]
        now = time.time()
        limit = self.max_requests + self.burst

        if len(bucket) < limit:
            bucket.append(now)
            self.total_allowed += 1
            return {
                "allowed": True,
                "remaining": limit - len(bucket),
                "reset_in": bucket[0] + self.window - now if bucket else 0,
            }

        self.total_denied += 1
        return {
            "allowed": False,
            "remaining": 0,
            "reset_in": bucket[0] + self.window - now if bucket else 0,
            "error": "rate_limit_exceeded",
        }

    def stats(self):
        return {
            "name": self.name,
            "total_allowed": self.total_allowed,
            "total_denied": self.total_denied,
        }

    def reset(self):
        self.buckets.clear()
        self.total_allowed = 0
        self.total_denied = 0


_limiters = {}


def get_limiter(name, **kwargs):
    if name not in _limiters:
        _limiters[name] = RateLimiter(name, **kwargs)
    return _limiters[name]
