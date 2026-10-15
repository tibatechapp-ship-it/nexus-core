"""HTTP transports for the SCM layer.

Layered, all standard-library, all offline-testable:

* :class:`UrllibTransport` — the production transport (``urllib`` only, so the
  autopilot runs on a phone with zero installs).
* :class:`RecordingTransport` — an in-memory double: records every request and
  replays canned responses, so the whole layer is exercised without a network.
* :class:`RateLimiter` — a token-bucket throttle with an injectable clock, so
  its *exact* behaviour is measured (never guessed).
* :class:`RateLimitedTransport` — wraps any transport, throttles calls and
  honours ``Retry-After`` on HTTP 429.
* :class:`CachingTransport` — caches successful GET responses (bounded + TTL)
  and reports real hit/miss statistics.

The wrappers implement the same :class:`~...base.Transport` protocol as the base
transports, so they stack: ``RateLimitedTransport(CachingTransport(Urllib...))``.
"""

from __future__ import annotations

import logging
import ssl
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable

from .base import Response, Transport, retry_after_seconds
from .exceptions import TransientError

logger = logging.getLogger("novamind.autopilot.scm")

__all__ = [
    "UrllibTransport",
    "RecordingTransport",
    "RecordedRequest",
    "RateLimiter",
    "RateLimitedTransport",
    "CachingTransport",
    "CacheStats",
]

TIMEOUT_DEFAULT = 20.0


@dataclass(frozen=True)
class RecordedRequest:
    """One request captured by :class:`RecordingTransport`."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None
    timeout: float


class UrllibTransport:
    """Default transport: :mod:`urllib` only, no third-party dependencies.

    Non-2xx statuses are returned as a :class:`~...base.Response` (so callers
    can inspect rate-limit headers); only transport-level failures raise.
    """

    def __init__(self, *, timeout: float = TIMEOUT_DEFAULT, verify_tls: bool = True) -> None:
        self.timeout = timeout
        self._context = ssl.create_default_context()
        if not verify_tls:  # pragma: no cover - only for local test servers
            self._context.check_hostname = False
            self._context.verify_mode = ssl.CERT_NONE

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float | None = None,
    ) -> Response:
        """Perform the HTTP request and return the raw response."""
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                request, timeout=timeout or self.timeout, context=self._context
            ) as resp:
                return Response(
                    status=getattr(resp, "status", 200),
                    headers={key: value for key, value in resp.headers.items()},
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:
            return Response(
                status=exc.code,
                headers={key: value for key, value in (exc.headers or {}).items()},
                body=exc.read() if hasattr(exc, "read") else b"",
            )
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))[:200]
            raise TransientError("network error: " + reason, status=0) from exc


class RecordingTransport:
    """In-memory transport double: records requests, replays queued responses."""

    def __init__(self, responses: Iterable[Response] | None = None) -> None:
        self._queue: deque[Response] = deque(responses or ())
        self.requests: list[RecordedRequest] = []

    def queue(self, *responses: Response) -> None:
        """Append more canned responses to replay."""
        self._queue.extend(responses)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = TIMEOUT_DEFAULT,
    ) -> Response:
        """Record the request and return the next queued response."""
        self.requests.append(RecordedRequest(method, url, dict(headers), body, timeout))
        if not self._queue:
            raise AssertionError(f"RecordingTransport has no response queued for {method} {url}")
        return self._queue.popleft()


class RateLimiter:
    """Client-side token-bucket rate limiter.

    ``rate`` tokens are produced every ``period`` seconds and at most ``burst``
    tokens exist at once — so ``rate=5, period=1.0`` allows 5 calls/second with a
    single-token burst. ``clock`` and ``sleep`` are injectable, so tests measure
    the *exact* throttling behaviour instead of sleeping in real time.
    """

    def __init__(
        self,
        *,
        rate: float,
        period: float = 1.0,
        burst: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if period <= 0:
            raise ValueError("period must be > 0")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self.rate = rate
        self.period = period
        self.burst = burst
        self._per_second = rate / period
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(burst)
        self._last = clock()
        self._not_before = 0.0

    def penalize(self, seconds: float) -> None:
        """Back off for ``seconds`` (e.g. from a ``Retry-After`` header)."""
        if seconds <= 0:
            return
        self._not_before = max(self._not_before, self._clock() + seconds)

    def acquire(self) -> float:
        """Wait until a request is allowed; return the seconds actually waited."""
        waited = 0.0
        now = self._clock()
        if now < self._not_before:
            delta = self._not_before - now
            self._sleep(delta)
            waited += delta
            now = self._clock()
        self._tokens = min(
            float(self.burst), self._tokens + (now - self._last) * self._per_second
        )
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return waited
        need = (1.0 - self._tokens) / self._per_second
        self._sleep(need)
        self._tokens = 0.0
        self._last = self._clock()
        return waited + need


class RateLimitedTransport:
    """Wrap a transport with client-side throttling and 429 back-off.

    Every call first waits on a :class:`RateLimiter`; a ``429`` response with a
    ``Retry-After`` header additionally penalises the limiter so the next call
    backs off for the server-requested duration.
    """

    def __init__(self, inner: Transport, limiter: RateLimiter) -> None:
        self._inner = inner
        self._limiter = limiter

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = TIMEOUT_DEFAULT,
    ) -> Response:
        """Throttle, delegate, and penalise the limiter on HTTP 429."""
        waited = self._limiter.acquire()
        if waited > 0:
            logger.debug("throttled %.3fs before %s %s", waited, method, url)
        resp = self._inner.request(method, url, headers=headers, body=body, timeout=timeout)
        if resp.status == 429:
            retry = retry_after_seconds(resp.headers)
            if retry > 0:
                self._limiter.penalize(retry)
                logger.warning("429 from %s — cooling down %.1fs", url, retry)
        return resp


@dataclass(frozen=True)
class CacheStats:
    """Real, measurable cache counters."""

    hits: int
    misses: int

    @property
    def hit_rate(self) -> float:
        """Cache hits divided by total lookups (``0.0`` when never used)."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class CachingTransport:
    """Cache successful ``GET`` responses (bounded + TTL) to cut redundant calls.

    Only ``GET`` requests are cached, and only 2xx responses. Eviction is
    FIFO-bounded by ``max_entries``. ``stats()`` returns real counters so cache
    effectiveness is *measured*, not claimed. ``clock`` is injectable for tests.
    """

    def __init__(
        self,
        inner: Transport,
        *,
        ttl: float = 60.0,
        max_entries: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._cache: dict[str, tuple[float, Response]] = {}
        self.hits = 0
        self.misses = 0

    def stats(self) -> CacheStats:
        """Return the real hit/miss counters."""
        return CacheStats(self.hits, self.misses)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = TIMEOUT_DEFAULT,
    ) -> Response:
        """Return a cached GET response when fresh, else delegate and store it."""
        if method != "GET":
            return self._inner.request(method, url, headers=headers, body=body, timeout=timeout)
        now = self._clock()
        cached = self._cache.get(url)
        if cached is not None and now - cached[0] < self.ttl:
            self.hits += 1
            logger.debug("cache hit %s", url)
            return cached[1]
        self.misses += 1
        resp = self._inner.request(method, url, headers=headers, body=body, timeout=timeout)
        if 200 <= resp.status < 300:
            self._store(url, now, resp)
        return resp

    def _store(self, url: str, now: float, resp: Response) -> None:
        if url in self._cache:
            del self._cache[url]
        elif len(self._cache) >= self.max_entries:
            evicted = next(iter(self._cache))
            del self._cache[evicted]
            logger.debug("cache evict %s", evicted)
        self._cache[url] = (now, resp)
