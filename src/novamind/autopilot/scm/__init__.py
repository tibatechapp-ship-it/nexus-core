"""Provider-agnostic source-control access for the autopilot (Slice 1).

Public surface: the read-only :class:`~...base.SCM` protocol, the write-side
:class:`~...base.SCMWriter` protocol (declared, not implemented), the neutral
value objects :class:`~...base.Issue` / :class:`~...base.Change`, the transport
seam, and the two concrete adapters :class:`GitHubSCM` / :class:`GitLabSCM`.
"""

from __future__ import annotations

import logging

from .base import (
    Change,
    Issue,
    Response,
    SCM,
    SCMWriter,
    Transport,
    as_int,
    label_names,
    normalize_state,
    retry_after_seconds,
)
from .exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
    SCMError,
    TransientError,
    error_for_status,
)
from .github import GitHubSCM
from .gitlab import GitLabSCM
from .transport import (
    CacheStats,
    CachingTransport,
    RateLimitedTransport,
    RateLimiter,
    RecordedRequest,
    RecordingTransport,
    UrllibTransport,
)

# Library best practice: attach a NullHandler so importing this package never
# emits "No handler found" warnings; the host application decides on handlers.
logging.getLogger("novamind.autopilot.scm").addHandler(logging.NullHandler())

__all__ = [
    # value objects
    "Issue",
    "Change",
    "Response",
    # contracts
    "SCM",
    "SCMWriter",
    "Transport",
    # adapters
    "GitHubSCM",
    "GitLabSCM",
    # transports
    "UrllibTransport",
    "RecordingTransport",
    "RecordedRequest",
    "RateLimiter",
    "RateLimitedTransport",
    "CachingTransport",
    "CacheStats",
    # errors
    "SCMError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "TransientError",
    "error_for_status",
    # helpers
    "normalize_state",
    "label_names",
    "as_int",
    "retry_after_seconds",
]
