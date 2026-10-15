"""Tests + real measurements for the resilient SCM transports.

The rate limiter and cache are driven by an injectable clock, so the numbers in
the assertions and the ``README`` are *measured properties of the code*, not
guesses — no sleeping, no network, fully deterministic.
"""

from __future__ import annotations

import json

import pytest

from src.novamind.autopilot.scm import (
    CacheStats,
    CachingTransport,
    RateLimitedTransport,
    RateLimiter,
    RecordingTransport,
    Response,
)


class FakeClock:
    """Deterministic clock: ``sleep`` advances ``now`` instead of blocking."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _resp(status: int, payload: object = None, headers: dict[str, str] | None = None) -> Response:
    body = b"" if payload is None else json.dumps(payload).encode()
    return Response(status=status, headers=headers or {}, body=body)


def _limiter(clock: FakeClock, *, rate: float = 5.0, burst: int = 1) -> RateLimiter:
    return RateLimiter(rate=rate, period=1.0, burst=burst, clock=clock.now, sleep=clock.sleep)


# ── RateLimiter ──────────────────────────────────────────────────────────────
def test_rate_limiter_allows_first_burst_immediately() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, rate=5.0, burst=3)
    assert [limiter.acquire() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert clock.t == 0.0


def test_rate_limiter_enforces_min_spacing_after_burst() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, rate=5.0, burst=1)
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == pytest.approx(0.2)  # 1 / rate
    assert clock.t == pytest.approx(0.2)


def test_rate_limiter_measured_throughput() -> None:
    # MEASUREMENT: 11 calls at rate=5/s, burst=1 -> 10 gaps x 0.2s = 2.00s.
    clock = FakeClock()
    limiter = _limiter(clock, rate=5.0, burst=1)
    total_waited = sum(limiter.acquire() for _ in range(11))
    assert clock.t == pytest.approx(2.0)
    assert total_waited == pytest.approx(2.0)


def test_rate_limiter_penalize_forces_cooldown() -> None:
    clock = FakeClock()
    limiter = _limiter(clock, rate=100.0)
    limiter.acquire()
    limiter.penalize(2.0)
    assert limiter.acquire() == pytest.approx(2.0)
    assert clock.t == pytest.approx(2.0)


def test_rate_limiter_penalize_ignores_non_positive() -> None:
    clock = FakeClock()
    limiter = _limiter(clock)
    limiter.penalize(0.0)
    assert limiter.acquire() == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [{"rate": 0.0}, {"rate": -1.0}, {"rate": 1.0, "period": 0.0}, {"rate": 1.0, "burst": 0}],
)
def test_rate_limiter_rejects_bad_configuration(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        RateLimiter(**kwargs)  # type: ignore[arg-type]


# ── RateLimitedTransport ─────────────────────────────────────────────────────
def test_rate_limited_transport_passes_response_through() -> None:
    inner = RecordingTransport([_resp(200, {"ok": True})])
    transport = RateLimitedTransport(inner, _limiter(FakeClock()))
    resp = transport.request("GET", "https://x/a", headers={})
    assert resp.status == 200
    assert inner.requests[0].url == "https://x/a"


def test_rate_limited_transport_honours_429_retry_after() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(429, {}, {"Retry-After": "3"}), _resp(200, {})])
    transport = RateLimitedTransport(inner, _limiter(clock, rate=1000.0))
    transport.request("GET", "https://x/a", headers={})  # 429 -> penalize(3)
    transport.request("GET", "https://x/a", headers={})  # must back off >= 3s
    assert clock.t >= 3.0


def test_rate_limited_transport_429_without_retry_after_does_not_penalize() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(429, {})])
    transport = RateLimitedTransport(inner, _limiter(clock, rate=1000.0))
    transport.request("GET", "https://x/a", headers={})
    assert clock.t == 0.0


# ── CachingTransport ─────────────────────────────────────────────────────────
def test_caching_transport_misses_then_hits() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(200, {"v": 1})])
    cache = CachingTransport(inner, ttl=60.0, clock=clock.now)
    first = cache.request("GET", "https://x/a", headers={})
    second = cache.request("GET", "https://x/a", headers={})
    assert first is second
    assert cache.stats() == CacheStats(hits=1, misses=1)
    assert cache.stats().hit_rate == pytest.approx(0.5)
    assert len(inner.requests) == 1


def test_caching_transport_measured_api_calls_saved() -> None:
    # MEASUREMENT: 10 identical GETs -> 1 upstream call, 9 saved, hit_rate 0.90.
    clock = FakeClock()
    inner = RecordingTransport([_resp(200, {"v": 1})])
    cache = CachingTransport(inner, ttl=60.0, clock=clock.now)
    for _ in range(10):
        cache.request("GET", "https://x/a", headers={})
    upstream_calls = len(inner.requests)
    assert upstream_calls == 1
    assert 10 - upstream_calls == 9  # api_calls_saved
    assert cache.stats().hit_rate == pytest.approx(0.9)


def test_caching_transport_ignores_non_get() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(200, {}), _resp(200, {})])
    cache = CachingTransport(inner, clock=clock.now)
    cache.request("POST", "https://x/a", headers={})
    cache.request("POST", "https://x/a", headers={})
    assert len(inner.requests) == 2
    assert cache.stats() == CacheStats(hits=0, misses=0)


def test_caching_transport_does_not_cache_errors() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(404, {}), _resp(200, {"v": 1})])
    cache = CachingTransport(inner, clock=clock.now)
    assert cache.request("GET", "https://x/a", headers={}).status == 404
    assert cache.request("GET", "https://x/a", headers={}).status == 200
    assert len(inner.requests) == 2
    assert cache.stats() == CacheStats(hits=0, misses=2)


def test_caching_transport_expires_after_ttl() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(200, {"v": 1}), _resp(200, {"v": 2})])
    cache = CachingTransport(inner, ttl=10.0, clock=clock.now)
    cache.request("GET", "https://x/a", headers={})
    clock.sleep(11.0)
    resp = cache.request("GET", "https://x/a", headers={})
    assert resp.body == json.dumps({"v": 2}).encode()
    assert cache.stats() == CacheStats(hits=0, misses=2)


def test_caching_transport_evicts_when_full() -> None:
    clock = FakeClock()
    inner = RecordingTransport(
        [_resp(200, {"a": 1}), _resp(200, {"b": 2}), _resp(200, {"a": 3})]
    )
    cache = CachingTransport(inner, ttl=60.0, max_entries=1, clock=clock.now)
    cache.request("GET", "https://x/a", headers={})
    cache.request("GET", "https://x/b", headers={})  # evicts a
    resp = cache.request("GET", "https://x/a", headers={})  # a gone -> miss
    assert resp.body == json.dumps({"a": 3}).encode()
    assert cache.stats() == CacheStats(hits=0, misses=3)


def test_caching_transport_refreshes_existing_key() -> None:
    clock = FakeClock()
    inner = RecordingTransport([_resp(200, {"v": 1}), _resp(200, {"v": 2})])
    cache = CachingTransport(inner, ttl=1.0, max_entries=1, clock=clock.now)
    cache.request("GET", "https://x/a", headers={})
    clock.sleep(2.0)
    cache.request("GET", "https://x/a", headers={})  # stale, url already cached
    assert len(inner.requests) == 2


def test_cache_stats_hit_rate_zero_when_unused() -> None:
    cache = CachingTransport(RecordingTransport(), clock=FakeClock().now)
    assert cache.stats().hit_rate == 0.0
