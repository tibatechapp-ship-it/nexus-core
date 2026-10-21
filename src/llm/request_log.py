"""LLM/orchestrator request log - append-only JSONL ledger.

Every completed POST /api/orchestrator/execute appends one record here
(v1.37.0). aggregate() exposes honest priority/failure-rate views.

Mirrors src/maintenance/task_log.py:
  * Env override read on every call -> hermetically testable.
  * Rotation at 10 MiB, 5 backups (.1 .. .5).
  * Append-only, never raises: a broken log degrades to a no-op.
  * One JSON object per line, flat, versioned by SCHEMA_VERSION.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5
MIN_SAMPLE = 100

_ENV_PATH = "NEXUS_REQUEST_LOG"
_ENV_MAX_BYTES = "NEXUS_REQUEST_LOG_MAX_BYTES"

_PRIORITIES = ("HIGH", "MED", "LOW")
_ALIASES = {
    "high": "HIGH",
    "HIGH": "HIGH",
    "med": "MED",
    "medium": "MED",
    "MED": "MED",
    "MEDIUM": "MED",
    "low": "LOW",
    "LOW": "LOW",
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _path() -> Path:
    override = os.environ.get(_ENV_PATH)
    if override:
        return Path(override).expanduser()
    try:
        data_dir = Path(__file__).resolve().parents[2] / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "request_log.jsonl"
    except OSError:
        return Path(tempfile.gettempdir()) / "nexus_request_log.jsonl"


def _max_bytes() -> int:
    raw = os.environ.get(_ENV_MAX_BYTES)
    if not raw:
        return MAX_BYTES
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return MAX_BYTES


def _rotate(path: Path) -> None:
    try:
        for i in range(BACKUPS, 0, -1):
            if i == 1:
                src = path
            else:
                src = path.with_name(path.name + "." + str(i - 1))
            dst = path.with_name(path.name + "." + str(i))
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
    except OSError:
        return


def record(
    priority: str,
    agent_id: str,
    outcome: str,
    reason: str | None = None,
) -> None:
    row: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "ts": _now(),
        "priority": _ALIASES.get(str(priority).lower(), "MED"),
        "agent_id": str(agent_id)[:120],
        "outcome": str(outcome)[:40],
    }
    if reason:
        row["reason"] = str(reason)[:200]
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            if path.stat().st_size >= _max_bytes():
                _rotate(path)
        except OSError:
            pass
    except Exception:
        return


def _parse_ts(raw: Any) -> datetime.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def aggregate(window_days: int = 7) -> dict[str, Any]:
    if not isinstance(window_days, int) or window_days < 1:
        window_days = 7
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=window_days
    )
    counts = {p: 0 for p in _PRIORITIES}
    failures = 0
    total = 0
    try:
        path = _path()
        if path.exists():
            for line in path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = _parse_ts(row.get("ts"))
                if ts is None or ts < cutoff:
                    continue
                total += 1
                key = _ALIASES.get(str(row.get("priority", "")).lower())
                if key:
                    counts[key] += 1
                if row.get("outcome") != "success":
                    failures += 1
    except Exception:
        pass
    return {
        "total_requests": total,
        "by_priority": counts,
        "failure_pct": round((failures / total) * 100.0, 2) if total else 0.0,
        "high_pct": round((counts["HIGH"] / total) * 100.0, 2) if total else 0.0,
        "sample_sufficient": total >= MIN_SAMPLE,
        "sampled_at": _now(),
    }
