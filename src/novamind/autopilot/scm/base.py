"""Provider-agnostic SCM contracts and value objects.

The autopilot talks to hosting platforms (GitHub, GitLab, ...) exclusively
through the :class:`SCM` protocol, so every worker is written once and runs on
every platform. Slice 1 exposes **read-only** access only; the write surface is
declared separately in :class:`SCMWriter` so read-only slices cannot mutate a
repository even by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

__all__ = [
    "Issue",
    "Change",
    "Response",
    "Transport",
    "SCM",
    "SCMWriter",
    "normalize_state",
    "label_names",
    "as_int",
    "retry_after_seconds",
]


# ── value objects ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Issue:
    """A provider-neutral issue."""

    platform: str
    id: int
    number: int
    title: str
    body: str
    state: str
    labels: tuple[str, ...]
    author: str
    url: str


@dataclass(frozen=True)
class Change:
    """A provider-neutral pull request (GitHub) / merge request (GitLab)."""

    platform: str
    id: int
    number: int
    title: str
    body: str
    state: str
    head: str
    base: str
    author: str
    url: str


@dataclass(frozen=True)
class Response:
    """A raw HTTP response as returned by a :class:`Transport`."""

    status: int
    headers: dict[str, str]
    body: bytes


# ── shared normalisation helpers ─────────────────────────────────────────────
_STATE_ALIASES: dict[str, str] = {
    "opened": "open",
    "open": "open",
    "closed": "closed",
    "merged": "merged",
    "locked": "locked",
}


def normalize_state(state: str) -> str:
    """Map a provider state name onto the neutral {open,closed,merged,locked} set."""
    return _STATE_ALIASES.get(state, state)


def label_names(raw: Iterable[Any] | None) -> tuple[str, ...]:
    """Normalise a label list — GitHub ``[{"name": ..}]`` or GitLab ``["a", ..]``."""
    if not raw:
        return ()
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            names.append(str(item.get("name", "")))
        else:
            names.append(str(item))
    return tuple(names)


def as_int(value: Any, default: int = 0) -> int:
    """Best-effort integer coercion for provider payloads."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def retry_after_seconds(headers: Mapping[str, str]) -> float:
    """Parse a ``Retry-After`` header (seconds) from a response, else ``0.0``."""
    raw = headers.get("Retry-After") or headers.get("retry-after") or ""
    try:
        return float(raw)
    except ValueError:
        return 0.0


# ── contracts ────────────────────────────────────────────────────────────────
class Transport(Protocol):
    """The tiny HTTP seam every adapter depends on.

    Production uses :class:`~src.novamind.autopilot.scm.transport.UrllibTransport`
    (standard library only); tests inject a recording double, so the whole SCM
    layer is exercised without a network.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = 20.0,
    ) -> Response:
        """Perform one HTTP request and return the raw response."""
        ...


@runtime_checkable
class SCM(Protocol):
    """Read-only access to a hosting platform."""

    platform: str

    def whoami(self) -> str:
        """Return the authenticated identity (login / username)."""
        ...

    def list_issues(
        self,
        *,
        labels: tuple[str, ...] = (),
        state: str = "open",
        limit: int = 20,
    ) -> list[Issue]:
        """Return up to ``limit`` issues, newest-activity first."""
        ...

    def get_issue(self, number: int) -> Issue:
        """Return a single issue by its per-repository number."""
        ...

    def list_changes(self, *, state: str = "open", limit: int = 20) -> list[Change]:
        """Return up to ``limit`` pull/merge requests, newest first."""
        ...

    def get_change(self, number: int) -> Change:
        """Return a single pull/merge request by its per-repository number."""
        ...


@runtime_checkable
class SCMWriter(Protocol):
    """Write access to a hosting platform — introduced in a later slice.

    Declared here so the read/write boundary is explicit: nothing in Slice 1
    implements this protocol, and the tests assert that.
    """

    def comment(self, number: int, body: str) -> None:
        """Post a comment on an issue or change."""
        ...

    def open_change(self, *, head: str, base: str, title: str, body: str) -> Change:
        """Open a pull/merge request."""
        ...

    def review(self, number: int, body: str) -> None:
        """Submit a review on a change."""
        ...
