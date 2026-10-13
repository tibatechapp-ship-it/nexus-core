"""Typed exceptions for the autopilot SCM layer.

Every adapter funnels HTTP and network failures through
:func:`error_for_status`, so callers branch on the *kind* of failure
(auth vs. rate-limit vs. transient) instead of parsing error strings.
"""

from __future__ import annotations

__all__ = [
    "SCMError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "TransientError",
    "error_for_status",
]


class SCMError(Exception):
    """Base class for every autopilot SCM failure."""

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class AuthError(SCMError):
    """Credentials are missing, invalid, or lack the required scope (HTTP 401/403)."""


class NotFoundError(SCMError):
    """The requested resource does not exist (HTTP 404)."""


class RateLimitError(SCMError):
    """The provider throttled us (HTTP 429, or 403 carrying rate-limit headers)."""

    def __init__(self, message: str, *, status: int = 0, retry_after: float = 0.0) -> None:
        super().__init__(message, status=status)
        self.retry_after = retry_after


class TransientError(SCMError):
    """A retryable condition: a network failure or a 5xx from the provider."""


def error_for_status(status: int, message: str = "", *, retry_after: float = 0.0) -> SCMError:
    """Map an HTTP status code (or ``0`` for a network failure) to a typed error.

    The mapping is the single place that decides "retry / give up / ask for
    credentials", so every adapter behaves identically:

    * ``0``            → :class:`TransientError` (could not reach the host)
    * ``404``          → :class:`NotFoundError`
    * ``429`` / ``403``+Retry-After → :class:`RateLimitError`
    * ``401`` / ``403`` → :class:`AuthError`
    * ``>= 500``       → :class:`TransientError`
    * anything else    → base :class:`SCMError`
    """
    detail = message or f"HTTP {status}"
    if status == 0:
        return TransientError(detail, status=status)
    if status == 404:
        return NotFoundError(detail, status=status)
    if status == 429 or (status == 403 and retry_after > 0.0):
        return RateLimitError(detail, status=status, retry_after=retry_after)
    if status in (401, 403):
        return AuthError(detail, status=status)
    if status >= 500:
        return TransientError(detail, status=status)
    return SCMError(detail, status=status)
