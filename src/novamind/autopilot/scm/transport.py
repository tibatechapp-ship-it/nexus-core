"""HTTP transports for the SCM layer.

:class:`UrllibTransport` is the production transport and uses only the Python
standard library, so the autopilot runs on a phone with zero installs.
:class:`RecordingTransport` is an in-memory double for tests: it records every
request and replays canned responses, so the whole layer is exercised offline.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .base import Response
from .exceptions import TransientError

__all__ = ["UrllibTransport", "RecordingTransport", "RecordedRequest"]

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
