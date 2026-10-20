"""Execution metrics for the orchestrator (read-only side-record).

Every call to ``/api/orchestrator/execute`` appends one compact record here.
The dashboard (``dashboard.py``) only ever READS the file — recording and
reporting are deliberately separate so a damaged log never blocks execution.

Design rules (kept intentionally small and dependency-free):

* Append-only, never raises: a broken or unwritable log degrades to a no-op.
* Bounded: the log keeps the most recent ``MAX_RECORDS`` entries so it cannot
  grow without limit on a phone.
* One JSON object per execution, flat and versioned by ``SCHEMA_VERSION``.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 2
MAX_RECORDS = 2000
_ENV_PATH = "NEXUS_METRICS_PATH"


def _utc_now() -> str:
    """Current UTC time as an ISO-8601 string with a trailing ``Z``."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _repo_root() -> Path:
    """Return the repository root (this file lives at ``<repo>/src/orchestrator``)."""
    return Path(__file__).resolve().parents[2]


def default_metrics_path() -> Path:
    """Resolve the metrics file: ``$NEXUS_METRICS_PATH`` else ``<repo>/data/metrics.json``."""
    override = os.getenv(_ENV_PATH)
    if override:
        return Path(override)
    repo_data = _repo_root() / "data"
    try:
        repo_data.mkdir(parents=True, exist_ok=True)
        return repo_data / "metrics.json"
    except OSError:  # pragma: no cover - only on a read-only filesystem
        return Path(tempfile.gettempdir()) / "nexus_metrics.json"


def _load(path: Path) -> list[dict[str, Any]]:
    """Read the log tolerantly: a missing/corrupt/wrong-shape file yields ``[]``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _atomic_write(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write ``rows`` atomically; never raises (best-effort persistence)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:  # pragma: no cover - best-effort only
        pass


def record(
    *,
    request: str,
    ok: bool,
    decomposed: bool,
    subtasks: list[Mapping[str, Any]],
    jury_fired: bool = False,
    risk: str | None = None,
    risk_reason: str | None = None,
    risk_matched: list[str] | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Append one execution record and return it (or ``None`` if it could not be saved).

    ``subtasks`` is the per-subtask result list; ``risk`` is the overall risk
    level when known (falls back to the highest subtask risk).

    ``risk_reason`` / ``risk_matched`` explain WHY the request was classified
    HIGH (e.g. ``"high:genome"`` + ``["genome"]`` from ``risk.explain()``). They
    are recorded only when the level is HIGH — a LOW/MED request does not need a
    reason, and omitting the keys keeps old and new rows the same flat shape.
    """
    target = path or default_metrics_path()
    agents = [str(s.get("agent", "")) for s in subtasks if s.get("agent")]
    failed = [str(s.get("agent", "")) for s in subtasks if not s.get("ok", True)]
    if risk is None:
        order = {"low": 0, "medium": 1, "high": 2}
        levels = [str(s.get("risk", "low")) for s in subtasks] or ["low"]
        risk = max(levels, key=lambda level: order.get(level, 0))
    entry: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "ts": _utc_now(),
        "request": request[:200],
        "ok": bool(ok),
        "decomposed": bool(decomposed),
        "n_subtasks": len(subtasks),
        "agents": agents,
        "failed_agents": failed,
        "jury_fired": bool(jury_fired),
        "risk": risk,
    }
    if str(risk) == "high":
        if risk_reason:
            entry["risk_reason"] = str(risk_reason)[:40]
        if risk_matched:
            entry["risk_matched"] = [str(m)[:40] for m in risk_matched][:10]
    rows = _load(target)
    rows.append(entry)
    _atomic_write(target, rows[-MAX_RECORDS:])
    return entry


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """Read all recorded executions (tolerant — never raises)."""
    return _load(path or default_metrics_path())
