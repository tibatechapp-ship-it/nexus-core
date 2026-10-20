"""Maintenance metrics surface — a read-only health view.

Pure aggregation over the genome's own ``stats()`` plus the maintenance task
ledger's real priority breakdown, exposed as JSON so a dashboard (or ``curl``)
can answer "how healthy is the agent fleet right now?" without importing
internal state.

The module is kept FastAPI-free at import time except for the router builder:
``register`` is what the gateway calls, and it uses
``app.router.routes.extend`` rather than ``include_router`` — the latter is
deferred in modern FastAPI and silently 404s through an ASGI ``mount``.

Read-only: it never writes to disk and never mutates the genome.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter

from . import task_log
from .task_generator import DEFAULT_LIMIT, MAX_LIMIT, generate_tasks

__all__ = ["build_router", "metrics_snapshot", "register"]


def _genome_stats() -> Dict[str, Any]:
    """Read the shared genome's aggregate counters, tolerating absence.

    The genome lives behind a lazy singleton; a missing or broken one degrades
    to an empty dict so the endpoint always answers (never raises).
    """
    try:
        from ..novamind.genome_v2 import get_genome_v2

        return dict(get_genome_v2().stats())
    except Exception:
        return {}


def _genome_document() -> Dict[str, Any]:
    """Read the shared genome as a ``{"agents": {...}}`` document.

    This is the shape ``task_generator.generate_tasks`` consumes (the same
    JSON-ready mapping ``GenomeV2.to_dict()`` produces). A missing/broken
    genome degrades to an empty document so task generation just yields none.
    """
    try:
        from ..novamind.genome_v2 import get_genome_v2

        return dict(get_genome_v2().to_dict())
    except Exception:
        return {}


def metrics_snapshot(
    *,
    fitness: Any = None,
    log: Optional[Any] = None,
    window_days: int = 7,
) -> Dict[str, Any]:
    """Compose the maintenance metrics payload.

    ``fitness`` is an optional genome-shaped object (``.stats()``) injected for
    tests; production reads the shared singleton. ``log`` is an optional override
    for the task-ledger path (also for tests).

    ``by_priority`` is the REAL breakdown read from the task ledger
    (``task_log.aggregate``) — a genuine count of generated/failed tasks by
    priority, not a placeholder. ``by_priority_all_time`` carries the
    un-windowed totals so a consumer can see the sample size behind the window.
    """
    if fitness is None:
        stats = _genome_stats()
    else:
        try:
            stats = dict(fitness.stats())
        except Exception:
            stats = {}

    try:
        ledger = task_log.aggregate(window_days=window_days, log=log)
    except Exception:
        ledger = {}

    window = ledger.get("window") or {}
    all_time = ledger.get("all_time") or {}
    by_priority: Dict[str, int] = dict(
        window.get("by_priority") or {"low": 0, "medium": 0, "high": 0}
    )
    by_priority_all_time: Dict[str, int] = dict(
        all_time.get("by_priority") or {"low": 0, "medium": 0, "high": 0}
    )

    return {
        "ok": True,
        "scope": "maintenance",
        "genome": {
            "agents": int(stats.get("agents", 0) or 0),
            "active": int(stats.get("active", 0) or 0),
            "retired": int(stats.get("retired", 0) or 0),
            "elite": int(stats.get("elite", 0) or 0),
            "probationary": int(stats.get("probationary", 0) or 0),
            "observations": int(stats.get("observations", 0) or 0),
            "task_observations": int(stats.get("task_observations", 0) or 0),
            "mean_fitness": stats.get("mean_fitness"),
        },
        "by_priority": by_priority,
        "by_priority_all_time": by_priority_all_time,
        "tasks": {
            "window_days": int(ledger.get("window_days", window_days) or window_days),
            "total_all_time": int(all_time.get("total_tasks", 0) or 0),
            "failure_pct": all_time.get("failure_pct", 0.0),
            "sample_sufficient": bool(ledger.get("is_sample_sufficient", False)),
        },
    }


def build_router() -> APIRouter:
    """Build the read-only maintenance metrics router."""
    router = APIRouter()

    @router.get("/api/maintenance/metrics")
    def maintenance_metrics(window_days: int = 7) -> Dict[str, Any]:
        """Aggregate fleet-health metrics (read-only, never raises)."""
        return metrics_snapshot(window_days=window_days)

    @router.get("/api/maintenance/tasks")
    def maintenance_tasks(limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
        """Candidate LOW/MED maintenance tasks from the current genome state."""
        try:
            genome = _genome_document()
            rows = [t.to_dict() for t in generate_tasks(genome, limit=limit)]
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "tasks": []}
        return {"ok": True, "limit": min(max(int(limit), 1), MAX_LIMIT), "tasks": rows}

    return router


def register(app: Any) -> APIRouter:
    """Attach the maintenance routes to ``app`` directly (no deferred include)."""
    router = build_router()
    app.router.routes.extend(router.routes)
    return router
