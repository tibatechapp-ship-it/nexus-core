"""Append-only log of generated maintenance tasks (pure, stdlib-only).

The genome answers "how healthy is the fleet?", but it has **no memory of the
tasks the maintenance layer proposes** — so a priority breakdown could only ever
be a placeholder. This module is the missing ledger: every generated task is
appended as one JSON line, and ``aggregate`` reads them back as real numbers.

Design rules (locked):

* ``record()`` **never raises** — maintenance must not fail because a log line
  could not be written.
* ``_log_path()`` is read on **every write** (not cached at import) so a test or
  operator that points ``NEXUS_TASK_LOG`` elsewhere between calls is honoured —
  the same trap that bit the genome's two import spellings.
* The default path is ``<repo>/data/task_log.jsonl``, deliberately **not**
  ``memory/``: ``memory/`` is guarded against test leaks, ``data/`` is not.
* ``aggregate()`` returns **two windows** (recent + all-time) and decides
  ``is_sample_sufficient`` on the **all-time** count, so an idle system with a
  long history is never reported as "insufficient".

Nothing here imports FastAPI or the genome: the ledger is a leaf.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "BACKUPS",
    "ENTRY_FIELDS",
    "LOW",
    "MAX_BYTES",
    "MED",
    "HIGH",
    "MIN_SAMPLE",
    "PRIORITIES",
    "aggregate",
    "log_path",
    "record",
    "read_entries",
]

LOW = "low"
MED = "medium"
HIGH = "high"

#: The stable priority vocabulary (mirrors ``task_generator``'s risk bands).
PRIORITIES = (LOW, MED, HIGH)

#: Fields every entry carries — kept as a constant so tests can assert the shape.
ENTRY_FIELDS = ("ts", "task_id", "priority", "agent_id", "outcome", "reason", "version")

#: Below this many all-time entries a percentage is reported as low-confidence.
MIN_SAMPLE = 30

#: Rotation thresholds — mirror ``security_gatekeeper`` (10 MiB, 5 backups).
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5

_OUTCOMES = ("generated", "failed", "skipped")


def _repo_root() -> Path:
    """The checkout root: ``<repo>/src/maintenance/task_log.py`` → parents[2]."""
    return Path(__file__).resolve().parents[2]


def log_path() -> Path:
    """Resolve the ledger path, reading the environment on **every** call.

    Order: ``$NEXUS_TASK_LOG`` → ``<repo>/data/task_log.jsonl`` → a temp-dir
    file. Never raises: an unusable repo dir falls back to the temp dir.
    """
    override = os.environ.get("NEXUS_TASK_LOG")
    if override:
        return Path(override)
    candidate = _repo_root() / "data" / "task_log.jsonl"
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        return Path(tempfile.gettempdir()) / "nexus_task_log.jsonl"


def _version() -> Optional[str]:
    """The running package version (live), or ``None`` if it cannot be read."""
    try:
        from src import __version__

        return str(__version__)
    except Exception:
        return None


def _rotate(path: Path) -> None:
    """Rotate ``path`` to ``path.1`` (and shift older backups) when it is big.

    Mirrors the gatekeeper policy: keep at most ``BACKUPS`` files, oldest
    discarded, never raises.
    """
    try:
        if not path.exists() or path.stat().st_size < MAX_BYTES:
            return
        for index in range(BACKUPS - 1, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            newer = path.with_name(f"{path.name}.{index + 1}")
            if older.exists():
                if index + 1 > BACKUPS:
                    older.unlink()
                else:
                    os.replace(older, newer)
        os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        pass


def record(
    *,
    priority: str,
    agent_id: str = "",
    outcome: str = "generated",
    reason: Optional[str] = None,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one task entry to the ledger; never raises.

    Returns the entry as written (useful for tests and logging). ``priority`` is
    normalised to the known vocabulary; unknown values are recorded verbatim so
    the ledger never lies about what it saw.
    """
    entry: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task_id": uuid.uuid4().hex,
        "priority": str(priority).strip().lower() or LOW,
        "agent_id": str(agent_id or ""),
        "outcome": str(outcome).strip().lower() if outcome in _OUTCOMES else "generated",
        "reason": None if reason is None else str(reason),
        "version": version if version is not None else _version(),
    }
    try:
        path = log_path()
        _rotate(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return entry


def read_entries(*, log: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read every well-formed entry; malformed lines are skipped.

    ``log`` overrides the resolved path (used by tests and by callers that
    already resolved it); the default resolves fresh on every call.
    """
    path = Path(log) if log is not None else log_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; a naive value is treated as UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _summarize(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Count a set of entries into the stable breakdown shape."""
    by_priority: Dict[str, int] = {name: 0 for name in PRIORITIES}
    for entry in entries:
        priority = str(entry.get("priority", "")).strip().lower()
        by_priority[priority] = by_priority.get(priority, 0) + 1
    total = len(entries)
    failed = sum(1 for e in entries if str(e.get("outcome", "")).lower() == "failed")
    failure_pct = round(100.0 * failed / total, 2) if total else 0.0
    return {
        "total_tasks": total,
        "by_priority": by_priority,
        "failed": failed,
        "failure_pct": failure_pct,
    }


def aggregate(
    *, window_days: int = 7, log: Optional[Path] = None
) -> Dict[str, Any]:
    """Summarise the ledger over a recent window **and** all time.

    ``is_sample_sufficient`` is decided on the **all-time** count (a quiet week
    on a system with a long history must not read as "insufficient"). Never
    raises: an unreadable ledger yields zeroed windows. ``log`` overrides the
    resolved path (tests / callers that already resolved it).
    """
    days = window_days if isinstance(window_days, int) and window_days > 0 else 7
    entries = read_entries(log=log)
    cutoff = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - days * 86400, tz=timezone.utc
    )

    recent: List[Dict[str, Any]] = [
        entry
        for entry in entries
        if (stamp := _parse_ts(entry.get("ts"))) is not None and stamp >= cutoff
    ]

    all_time = _summarize(entries)
    return {
        "window_days": days,
        "window": _summarize(recent),
        "all_time": all_time,
        "is_sample_sufficient": all_time["total_tasks"] >= MIN_SAMPLE,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }
