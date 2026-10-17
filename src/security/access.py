"""Access control for the HTTP surface — token auth, rate limit, audit log.

All three are **stdlib-only and FastAPI-free**: :meth:`AccessGuard.check` takes
plain ``method`` / ``headers`` / ``client`` values, so the whole policy can be
unit-tested without a server and reused by any ASGI app (the unified gateway
installs it as one HTTP middleware).

Defaults are chosen for a phone-bound local server:

* **auth OFF** — nothing to do until ``NEXUS_AUTH_TOKEN`` is set (the gateway
  binds 127.0.0.1); when set, every mutating request needs ``X-Auth-Token``.
* **rate limit ON** — :data:`DEFAULT_RATE` requests per :data:`DEFAULT_WINDOW`
  seconds per client+route; ``NEXUS_RATE_LIMIT=0`` disables it.
* **audit OFF** — no surprise disk writes; set ``NEXUS_AUDIT_LOG`` to a path to
  record every mutating call as one JSON line.

Only mutating methods (:data:`MUTATING_METHODS`) are gated: reads stay free, so
dashboards and probes never need a token.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

#: Methods that change state (or spend money) — everything else is a read.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

TOKEN_ENV = "NEXUS_AUTH_TOKEN"
TOKEN_HEADER = "x-auth-token"
RATE_ENV = "NEXUS_RATE_LIMIT"
WINDOW_ENV = "NEXUS_RATE_WINDOW"
AUDIT_ENV = "NEXUS_AUDIT_LOG"

DEFAULT_RATE = 120
DEFAULT_WINDOW = 60.0
AUDIT_MAX_BYTES = 1_000_000

_OFF_VALUES = frozenset({"", "0", "off", "no", "false", "none"})


@dataclass(frozen=True)
class Decision:
    """Result of one :meth:`AccessGuard.check`.

    ``allowed`` False means refuse the request with ``status`` (401 for a bad
    token, 429 once the rate limit is hit) and ``error`` as the JSON message.
    """

    allowed: bool
    status: int = 200
    error: str = ""
    retry_after: float = 0.0


_ALLOWED = Decision(allowed=True)


def _is_off(value: str) -> bool:
    """True when an env value means "disabled"."""
    return value.strip().lower() in _OFF_VALUES


def _float_env(value: Optional[str], default: float) -> float:
    """Parse an env value as float, falling back to ``default``."""
    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _int_env(value: Optional[str], default: int) -> int:
    """Parse an env value as int, falling back to ``default``."""
    if value is None:
        return default
    try:
        return int(float(value.strip()))
    except ValueError:
        return default


class RateLimiter:
    """Fixed-window counter per key (client + route).

    ``allow(key)`` returns ``0.0`` when the call is permitted, otherwise the
    seconds left in the current window — the value the HTTP layer reports as
    ``Retry-After``.  ``clock`` is injectable so the window can be tested
    without sleeping.
    """

    def __init__(self, rate: int = DEFAULT_RATE, window: float = DEFAULT_WINDOW,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.rate = int(rate)
        self.window = float(window)
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: Dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        """A limiter needs a positive rate *and* a positive window."""
        return self.rate > 0 and self.window > 0.0

    def allow(self, key: str) -> float:
        """Count one call for ``key``; return 0.0 if allowed, else the wait."""
        if not self.enabled:
            return 0.0
        now = self._clock()
        with self._lock:
            start, count = self._seen.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            if count >= self.rate:
                self._seen[key] = (start, count)
                return max(0.0, self.window - (now - start))
            self._seen[key] = (start, count + 1)
        return 0.0

    def reset(self) -> None:
        """Drop every counter (used by tests and by explicit reloads)."""
        with self._lock:
            self._seen.clear()


class AuditLog:
    """Append-only JSONL audit log, rotated once past ``max_bytes``.

    Disabled (no path) by default: :meth:`write` still returns the record so
    callers can log it elsewhere, it simply does not touch the disk.
    """

    def __init__(self, path: Optional[Any] = None, *,
                 max_bytes: int = AUDIT_MAX_BYTES,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else None
        self.max_bytes = int(max_bytes)
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """True when the log has a destination on disk."""
        return self.path is not None

    def write(self, event: str, **fields: Any) -> Dict[str, Any]:
        """Record one event; returns the row (never raises on I/O trouble)."""
        record = {"ts": round(self._clock(), 3), "event": event}
        record.update(fields)
        if self.path is None:
            return record
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                    os.replace(self.path, self.path.with_name(self.path.name + ".1"))
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass  # auditing must never take the server down
        return record


class AccessGuard:
    """Token + rate limit + audit, composed and ready for one ASGI app."""

    def __init__(self, *, token: str = "", header: str = TOKEN_HEADER,
                 limiter: Optional[RateLimiter] = None,
                 audit: Optional[AuditLog] = None,
                 methods: Any = MUTATING_METHODS) -> None:
        self.token = token
        self.header = header
        self.limiter = limiter
        self.audit = audit if audit is not None else AuditLog()
        self.methods = frozenset(m.upper() for m in methods)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None, *,
                 clock: Optional[Callable[[], float]] = None) -> "AccessGuard":
        """Build a guard from the environment (every knob optional).

        ``NEXUS_AUTH_TOKEN``      shared secret (off when unset)
        ``NEXUS_RATE_LIMIT``      requests per window, ``0`` disables
        ``NEXUS_RATE_WINDOW``     window length in seconds
        ``NEXUS_AUDIT_LOG``       JSONL path, or ``off`` for none
        """
        source: Mapping[str, str] = os.environ if env is None else env
        token = (source.get(TOKEN_ENV) or "").strip()
        rate = _int_env(source.get(RATE_ENV), DEFAULT_RATE)
        window = _float_env(source.get(WINDOW_ENV), DEFAULT_WINDOW)
        audit_raw = (source.get(AUDIT_ENV) or "").strip()
        audit_path = None if _is_off(audit_raw) else audit_raw
        return cls(
            token=token,
            limiter=RateLimiter(rate, window, clock=clock or time.monotonic),
            audit=AuditLog(audit_path),
        )

    @property
    def auth_enabled(self) -> bool:
        """True when a token is required on mutating calls."""
        return bool(self.token)

    @property
    def rate_enabled(self) -> bool:
        """True when the limiter is active."""
        return self.limiter is not None and self.limiter.enabled

    def check(self, method: str, path: str, headers: Mapping[str, str],
              client: str = "") -> Decision:
        """Decide one request: reads pass, writes need token + rate budget."""
        verb = (method or "").upper()
        if verb not in self.methods:
            return _ALLOWED
        if self.token:
            provided = ""
            try:
                provided = str(headers.get(self.header, ""))
            except AttributeError:  # a non-mapping header bag
                provided = ""
            if not (provided and hmac.compare_digest(provided, self.token)):
                return Decision(False, 401, f"unauthorized: {self.header} required")
        if self.limiter is not None:
            wait = self.limiter.allow(f"{client or '-'}|{verb}|{path}")
            if wait > 0.0:
                return Decision(False, 429, "rate limit exceeded",
                                round(wait, 3))
        return _ALLOWED

    def record(self, decision: Decision, method: str, path: str,
               client: str = "", **fields: Any) -> Dict[str, Any]:
        """Write one audit row for a request.

        The middleware records every call (the guard only *refuses* mutating
        ones), so reads appear in the log too.  ``**fields`` overrides the
        defaults: the middleware passes the status the request ACTUALLY
        produced, so a 404 is recorded as 404 and not as the status the
        decision only predicted.
        """
        row: Dict[str, Any] = {
            "method": (method or "").upper(),
            "path": path,
            "client": client or "-",
            "status": decision.status,
            "allowed": decision.allowed,
        }
        row.update(fields)
        return self.audit.write("http", **row)


    def stats(self) -> Dict[str, Any]:
        """Config summary for ``/api/status`` (never leaks the token)."""
        limiter = self.limiter if self.rate_enabled else None
        return {
            "auth": self.auth_enabled,
            "header": self.header,
            "rate": limiter.rate if limiter is not None else 0,
            "window": limiter.window if limiter is not None else 0.0,
            "audit": str(self.audit.path) if self.audit.enabled else None,
            "methods": sorted(self.methods),
        }


__all__ = [
    "AccessGuard",
    "AuditLog",
    "Decision",
    "RateLimiter",
    "MUTATING_METHODS",
    "TOKEN_HEADER",
    "TOKEN_ENV",
    "RATE_ENV",
    "WINDOW_ENV",
    "AUDIT_ENV",
    "DEFAULT_RATE",
    "DEFAULT_WINDOW",
]
