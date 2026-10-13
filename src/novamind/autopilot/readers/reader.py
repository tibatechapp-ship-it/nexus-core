"""The issue reader — turn provider issues into ranked, de-duplicated tasks.

:class:`IssueReader` is the Slice 2 shell: it fetches issues through any
:class:`~src.novamind.autopilot.scm.base.SCM` (GitHub or GitLab, unchanged) and
maps each into a :class:`~...task.Task` using the pure helpers in
:mod:`...classify`. The module also exposes three *pure* list transforms —
:func:`dedupe`, :func:`rank`, :func:`select` — so callers compose exactly the
set they need.

Everything is read-only and offline-testable: the reader never writes, and the
classification has no I/O, so a fake SCM is enough to exercise the whole slice.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from ..scm.base import Issue, SCM
from .classify import (
    classify_kind,
    classify_priority,
    extract_areas,
    extract_criteria,
    extract_references,
    needs_more_info,
)
from .task import Task, fingerprint, kind_rank, priority_rank

__all__ = ["IssueReader", "dedupe", "rank", "select"]


class IssueReader:
    """Read issues from an :class:`SCM` and normalise them into :class:`Task`s.

    The reader holds no state beyond its configuration, so a single instance may
    be reused for many reads.
    """

    def __init__(self, scm: SCM, *, min_body_words: int = 8) -> None:
        self._scm = scm
        #: A body with fewer meaningful words and no criteria is "needs info".
        self._min_body_words = min_body_words

    @property
    def platform(self) -> str:
        """The platform the underlying SCM talks to (``github``/``gitlab``)."""
        return self._scm.platform

    def to_task(self, issue: Issue) -> Task:
        """Map a single raw :class:`Issue` into a structured :class:`Task`."""
        labels = tuple(issue.labels)
        kind = classify_kind(issue.title, issue.body, labels)
        criteria = extract_criteria(issue.body)
        return Task(
            platform=issue.platform,
            number=issue.number,
            title=issue.title,
            body=issue.body,
            url=issue.url,
            author=issue.author,
            state=issue.state,
            labels=labels,
            kind=kind,
            priority=classify_priority(labels),
            areas=extract_areas(issue.title, issue.body, labels),
            criteria=criteria,
            references=extract_references(issue.title, issue.body),
            needs_info=needs_more_info(
                body=issue.body, criteria=criteria, labels=labels, min_words=self._min_body_words
            ),
            fingerprint=fingerprint(issue.title, kind),
        )

    def read(
        self,
        *,
        labels: tuple[str, ...] = (),
        state: str = "open",
        limit: int = 20,
    ) -> list[Task]:
        """Fetch up to ``limit`` issues and map each into a :class:`Task`."""
        return [self.to_task(issue) for issue in self._scm.list_issues(labels=labels, state=state, limit=limit)]

    def read_one(self, number: int) -> Task:
        """Fetch and map a single issue by its per-repository number."""
        return self.to_task(self._scm.get_issue(number))

    def collect(
        self,
        *,
        labels: tuple[str, ...] = (),
        state: str = "open",
        limit: int = 20,
        kinds: Iterable[str] = (),
        priority_max: str | None = None,
        areas: Iterable[str] = (),
        include_needs_info: bool = True,
    ) -> list[Task]:
        """Read, de-duplicate, filter and rank in one call.

        This is the convenience entry point most callers want: it composes
        :meth:`read`, :func:`dedupe`, :func:`select` and :func:`rank`.
        """
        tasks = self.read(labels=labels, state=state, limit=limit)
        tasks = dedupe(tasks)
        tasks = select(
            tasks,
            kinds=kinds,
            priority_max=priority_max,
            areas=areas,
            include_needs_info=include_needs_info,
        )
        return rank(tasks)


# ── pure list transforms ─────────────────────────────────────────────────────
def dedupe(tasks: Sequence[Task]) -> list[Task]:
    """Drop tasks whose :attr:`~...task.Task.fingerprint` was already seen.

    The first occurrence wins, so upstream ordering (newest-activity first) is
    preserved for the surviving representative.
    """
    seen: set[str] = set()
    unique: list[Task] = []
    for task in tasks:
        if task.fingerprint in seen:
            continue
        seen.add(task.fingerprint)
        unique.append(task)
    return unique


def rank(tasks: Sequence[Task]) -> list[Task]:
    """Sort tasks most-urgent first: priority, then kind, then title."""
    return sorted(tasks, key=lambda task: (priority_rank(task.priority), kind_rank(task.kind), task.title.lower()))


def select(
    tasks: Sequence[Task],
    *,
    kinds: Iterable[str] = (),
    priority_max: str | None = None,
    areas: Iterable[str] = (),
    include_needs_info: bool = True,
) -> list[Task]:
    """Filter tasks by kind, a priority ceiling and/or affected areas.

    ``priority_max`` keeps tasks at least as urgent as the given priority
    (e.g. ``"p1"`` keeps p0 and p1). ``areas`` matches any overlap. Setting
    ``include_needs_info=False`` drops tasks that still need a reply.
    """
    wanted_kinds = set(kinds)
    wanted_areas = set(areas)
    ceiling = priority_rank(priority_max) if priority_max is not None else None
    chosen: list[Task] = []
    for task in tasks:
        if wanted_kinds and task.kind not in wanted_kinds:
            continue
        if ceiling is not None and priority_rank(task.priority) > ceiling:
            continue
        if wanted_areas and not wanted_areas.intersection(task.areas):
            continue
        if not include_needs_info and task.needs_info:
            continue
        chosen.append(task)
    return chosen
