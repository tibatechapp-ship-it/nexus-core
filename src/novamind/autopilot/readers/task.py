"""Structured work items produced by the autopilot readers (Slice 2).

A raw :class:`~src.novamind.autopilot.scm.base.Issue` is provider-shaped prose;
what the autopilot actually reasons about is a **task** — a normalised,
deterministic record it can classify, rank, hand to the Council and (in a later
slice) act on.

This module defines that record (:class:`Task`) and the small *pure* helpers
that keep it stable across runs and platforms: title normalisation, a
content-derived fingerprint for de-duplication, and priority ordering. Nothing
here touches the network or the clock, so it is fully unit-testable on a phone.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Task",
    "KINDS",
    "PRIORITIES",
    "KIND_BUG",
    "KIND_FEATURE",
    "KIND_DOCS",
    "KIND_QUESTION",
    "KIND_CHORE",
    "KIND_OTHER",
    "PRIORITY_NONE",
    "normalize_title",
    "fingerprint",
    "priority_rank",
    "kind_rank",
]

# ── enums-as-constants (stdlib-only: no Enum ceremony for fixed token sets) ───
KIND_BUG = "bug"
KIND_FEATURE = "feature"
KIND_DOCS = "docs"
KIND_QUESTION = "question"
KIND_CHORE = "chore"
KIND_OTHER = "other"

#: All recognised task kinds, ordered by processing weight (bugs first).
KINDS: tuple[str, ...] = (
    KIND_BUG,
    KIND_FEATURE,
    KIND_DOCS,
    KIND_QUESTION,
    KIND_CHORE,
    KIND_OTHER,
)

PRIORITY_NONE = "none"

#: Priorities from most to least urgent; a task always carries one of these.
PRIORITIES: tuple[str, ...] = ("p0", "p1", "p2", "p3", PRIORITY_NONE)

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    """Lower-case, strip punctuation and collapse whitespace.

    The normalised form is the basis for de-duplication: two issues filed on
    different platforms with the same title must collapse to one task.
    """
    lowered = title.strip().lower()
    squashed = _NON_ALNUM.sub(" ", lowered)
    return _WS.sub(" ", squashed).strip()


def fingerprint(title: str, kind: str = "") -> str:
    """A short, stable content hash used to de-duplicate tasks.

    Derived from the *normalised title* (and kind) only — deliberately ignoring
    platform and issue number — so the same problem reported twice is one task.
    """
    basis = f"{kind}:{normalize_title(title)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def priority_rank(priority: str) -> int:
    """Return the sort index of ``priority`` (0 = most urgent, last = none)."""
    try:
        return PRIORITIES.index(priority)
    except ValueError:
        return len(PRIORITIES) - 1


def kind_rank(kind: str) -> int:
    """Return the sort index of ``kind`` (0 = bug, last = other)."""
    try:
        return KINDS.index(kind)
    except ValueError:
        return len(KINDS) - 1


@dataclass(frozen=True)
class Task:
    """A provider-neutral, actionable unit of work parsed from an issue.

    ``Task`` is the autopilot's lingua franca: readers emit it, the Council
    debates it, and (later) writers act on it. It is frozen so it can be safely
    shared across workers.
    """

    platform: str
    number: int
    title: str
    body: str
    url: str
    author: str
    state: str
    labels: tuple[str, ...]
    kind: str
    priority: str
    areas: tuple[str, ...]
    criteria: tuple[str, ...]
    references: tuple[str, ...]
    needs_info: bool
    fingerprint: str

    #: `needs_info` is a heuristic, not a hard gate — expose the easy read.
    @property
    def ready(self) -> bool:
        """True when the task carries enough detail to act on without a reply."""
        return not self.needs_info

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view (tuples become lists, ready is derived)."""
        return {
            "platform": self.platform,
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "author": self.author,
            "state": self.state,
            "labels": list(self.labels),
            "kind": self.kind,
            "priority": self.priority,
            "areas": list(self.areas),
            "criteria": list(self.criteria),
            "references": list(self.references),
            "needs_info": self.needs_info,
            "fingerprint": self.fingerprint,
            "ready": self.ready,
        }

    def summary(self) -> str:
        """A one-line human label, e.g. ``[p1 bug] login fails (#42)``."""
        return f"[{self.priority} {self.kind}] {self.title} (#{self.number})"
