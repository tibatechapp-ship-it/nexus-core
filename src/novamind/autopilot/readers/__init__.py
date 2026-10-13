"""Turn repository issues into structured, ranked work (Slice 2).

Public surface: :class:`~...reader.IssueReader` (fetch an issue through any
:class:`~src.novamind.autopilot.scm.base.SCM` and normalise it), the
:class:`~...task.Task` value object it emits, the pure list transforms
(:func:`~...reader.dedupe`, :func:`~...reader.rank`, :func:`~...reader.select`)
and the classification helpers. Nothing here writes, and nothing touches the
network except through the injected SCM.
"""

from __future__ import annotations

import logging

from .classify import (
    classify_kind,
    classify_priority,
    extract_areas,
    extract_criteria,
    extract_references,
    needs_more_info,
)
from .reader import IssueReader, dedupe, rank, select
from .task import (
    KINDS,
    PRIORITIES,
    Task,
    fingerprint,
    kind_rank,
    normalize_title,
    priority_rank,
)

# Attach a NullHandler so importing never warns; the host app owns handlers.
logging.getLogger("novamind.autopilot.readers").addHandler(logging.NullHandler())

__all__ = [
    # orchestrator
    "IssueReader",
    # transforms
    "dedupe",
    "rank",
    "select",
    # value object + constants
    "Task",
    "KINDS",
    "PRIORITIES",
    # pure helpers
    "classify_kind",
    "classify_priority",
    "extract_areas",
    "extract_criteria",
    "extract_references",
    "needs_more_info",
    "normalize_title",
    "fingerprint",
    "priority_rank",
    "kind_rank",
]
