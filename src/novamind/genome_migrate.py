"""One-way import of the legacy SQLite genome into the canonical v2 genome.

P3 made :mod:`src.novamind.genome_v2` the single source of truth
(``docs/GENOME_UNIFICATION.md``).  Deployments that have been running since
before that decision still hold history in the legacy ``agent_genome`` table of
``sessions.db``; this module folds it in **once**, at install time, so nobody
loses their standings and nobody keeps two live copies.

Two properties matter more than speed here:

* **Additive only** — :meth:`GenomeV2Adapter.import_` takes ``max()`` of the
  counters it merges, so running the import twice cannot inflate a row.
* **Never fatal** — a missing/old/corrupt SQLite file is the normal case on a
  fresh install.  Everything is wrapped and reported by count, not by exception.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .genome.adapter import GenomeV2Adapter
from .genome_v2 import GenomeV2, get_genome_v2

__all__ = ["import_v1_rows", "import_v1_store", "migrate_if_fresh"]


def _legacy_rows(store: Any) -> list[dict[str, Any]]:
    """Legacy genome rows from a ``SessionStore`` (empty on any failure)."""
    try:
        rows = store.list_agents()
    except Exception:
        return []
    return [dict(r) for r in rows or [] if isinstance(r, dict)]


def import_v1_rows(rows: Any, genome: Optional[GenomeV2] = None) -> int:
    """Fold legacy rows into ``genome`` (default: the process-wide genome)."""
    target = genome if genome is not None else get_genome_v2()
    try:
        return GenomeV2Adapter(target).import_({"agents": list(rows or [])})
    except Exception:  # pragma: no cover - importing history must not crash
        return 0


def import_v1_store(store: Any, genome: Optional[GenomeV2] = None) -> int:
    """Import every legacy row from ``store`` into the v2 genome."""
    return import_v1_rows(_legacy_rows(store), genome)


def migrate_if_fresh(store: Any, genome_path: Optional[Path] = None,
                     genome: Optional[GenomeV2] = None) -> int:
    """Import the legacy genome *only* when the v2 store does not exist yet.

    ``genome_path`` is the JSON file the v2 genome is persisted to
    (:func:`src.novamind.genome_store.default_path`).  When it already exists the
    canonical store is in charge and a second import would only add noise, so
    the function returns ``0`` without touching anything.
    """
    try:
        if genome_path is not None and Path(genome_path).exists():
            return 0
    except OSError:  # pragma: no cover - unreadable path == "cannot prove fresh"
        return 0
    return import_v1_store(store, genome)
