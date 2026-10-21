#!/usr/bin/env python3
"""Memory retention — prune the episodic log so it cannot grow without bound.

``MemoryManager.retention()`` existed but was never called outside tests, so in
production the episodic store grew forever.  This script is the production
entry point: run it from cron (or by hand) to apply an age and/or size cap.

Dry-run BY DEFAULT — nothing is deleted until you pass ``--apply``.

Usage:
    python3 scripts/retention.py                      # report what WOULD be removed
    python3 scripts/retention.py --apply              # actually delete
    python3 scripts/retention.py --max-age-days 30 --max-episodes 5000 --apply

Environment overrides (all optional):
    NEXUS_MEMORY_DB        memory database path (default: the manager's default)
    NEXUS_RETENTION_DAYS   default for --max-age-days
    NEXUS_RETENTION_EPISODES   default for --max-episodes
    NEXUS_RETENTION_LOG    log file (default: <repo>/data/retention.log)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _default_log() -> Path:
    return Path(os.environ.get("NEXUS_RETENTION_LOG", str(_REPO_ROOT / "data" / "retention.log")))


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int(name: str) -> int | None:
    value = _env_float(name)
    return int(value) if value is not None else None


def resolve_policy(
    max_age_days: float | None, max_episodes: int | None
) -> tuple[float | None, int | None]:
    """Fill missing caps from env; a non-positive cap means "unset"."""
    if max_age_days is None:
        max_age_days = _env_float("NEXUS_RETENTION_DAYS")
    if max_episodes is None:
        max_episodes = _env_int("NEXUS_RETENTION_EPISODES")
    if max_age_days is not None and max_age_days <= 0:
        max_age_days = None
    if max_episodes is not None and max_episodes <= 0:
        max_episodes = None
    return max_age_days, max_episodes


def run(
    *,
    apply: bool,
    max_age_days: float | None,
    max_episodes: int | None,
    db_path: str | None = None,
    clock: Any = None,
) -> dict[str, Any]:
    """Apply (or preview) retention; never raises — returns a report dict."""
    from src.memory.manager import MemoryManager

    max_age_days, max_episodes = resolve_policy(max_age_days, max_episodes)
    report: dict[str, Any] = {
        "applied": bool(apply),
        "max_age_days": max_age_days,
        "max_episodes": max_episodes,
        "before": 0,
        "removed": 0,
        "after": 0,
        "error": None,
    }
    if max_age_days is None and max_episodes is None:
        report["error"] = "no policy: set --max-age-days / --max-episodes (or env)"
        return report

    kwargs: dict[str, Any] = {}
    if db_path is not None:
        kwargs["path"] = db_path
    if clock is not None:
        kwargs["clock"] = clock
    manager = MemoryManager(**kwargs)
    try:
        report["before"] = _episode_count(manager)
        if apply:
            result = manager.retention(
                max_age_days=max_age_days, max_episodes=max_episodes
            )
            report["removed"] = int(sum(result.values())) if result else 0
        else:
            report["removed"] = _episodes_that_would_go(
                manager, max_age_days, max_episodes
            )
        report["after"] = _episode_count(manager)
    except Exception as exc:  # pragma: no cover - defensive; never break cron
        report["error"] = str(exc)
    finally:
        try:
            manager.close()
        except Exception:  # pragma: no cover - defensive
            pass
    return report


def _episode_count(manager: Any) -> int:
    row = manager.connection.execute("SELECT COUNT(*) FROM episodes").fetchone()
    return int(row[0]) if row else 0


def _episodes_that_would_go(
    manager: Any, max_age_days: float | None, max_episodes: int | None
) -> int:
    """Count rows a retention run WOULD delete (dry-run), read-only."""
    from src.memory.manager import DAY

    doomed: set[int] = set()
    if max_age_days is not None:
        cutoff = manager._clock() - float(max_age_days) * DAY
        rows = manager.connection.execute(
            "SELECT id FROM episodes WHERE ts < ?", (cutoff,)
        ).fetchall()
        doomed.update(int(r[0]) for r in rows)
    if max_episodes is not None:
        rows = manager.connection.execute(
            """
            SELECT id FROM episodes WHERE id NOT IN (
                SELECT id FROM episodes ORDER BY ts DESC, id DESC LIMIT ?
            )
            """,
            (int(max_episodes),),
        ).fetchall()
        doomed.update(int(r[0]) for r in rows)
    return len(doomed)


def _log(report: dict[str, Any]) -> None:
    try:
        path = _default_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **report,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - logging must never fail the run
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune the episodic memory log.")
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default: dry-run)")
    parser.add_argument("--max-age-days", type=float, default=None,
                        help="drop episodes older than N days")
    parser.add_argument("--max-episodes", type=int, default=None,
                        help="keep only the newest N episodes")
    parser.add_argument("--db", default=None, help="memory database path override")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = run(
        apply=args.apply,
        max_age_days=args.max_age_days,
        max_episodes=args.max_episodes,
        db_path=args.db,
    )
    _log(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        mode = "APPLIED" if report["applied"] else "DRY-RUN"
        print(f"[{mode}] episodes before={report['before']} "
              f"removed={report['removed']} after={report['after']}")
        if report["error"]:
            print(f"  ! {report['error']}")
    return 1 if report["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
