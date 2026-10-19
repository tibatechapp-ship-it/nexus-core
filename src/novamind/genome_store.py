"""Disk persistence for the Agent Genome v2 — load / save / seed.

:mod:`src.novamind.genome_v2` is deliberately pure (no I/O, no clock).  This
module holds the *only* disk touch-point for the genome, so a deployed gateway
keeps its agent standoffs across `sv restart` while the model itself stays
hermetic and unit-testable offline.

Where the file lives — first hit wins:

1. ``$NEXUS_GENOME_PATH`` (explicit override — used by the test-suite);
2. a sibling of the training DB (folder of ``$NEXUS_TRAINING_DB`` / ``$NEXUS_DB``,
   so a deployed instance keeps all its data together);
3. ``<repo>/data/genome.json``;
4. a temp dir (read-only installs).

Writes are atomic (temp file + ``os.replace``) and never raise: fitness
bookkeeping must never take a request down.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .genome_v2 import (
    GenomeV2,
    get_genome_v2,
    set_genome_v2,
    set_persistence_hook,
)

__all__ = [
    "ENV_GENOME_PATH",
    "default_path",
    "load",
    "save",
    "install",
]

#: Environment variable that overrides the genome file path.
ENV_GENOME_PATH = "NEXUS_GENOME_PATH"


def _repo_root() -> Path:
    """Best-effort repo root, derived from this file's location.

    This file is ``<repo>/src/novamind/genome_store.py``, so the root is
    ``parents[2]`` (``parents[3]`` would be *outside* the repo — the training
    store sits one level deeper in ``.../novamind/training/`` and uses 3).
    """
    return Path(__file__).resolve().parents[2]


def default_path() -> Path:
    """Resolve the genome file path (see the module docstring for the order)."""
    explicit = os.environ.get(ENV_GENOME_PATH)
    if explicit:
        return Path(explicit)
    sibling = os.environ.get("NEXUS_TRAINING_DB") or os.environ.get("NEXUS_DB")
    if sibling:
        return Path(sibling).with_name("genome.json")
    data_dir = _repo_root() / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "genome.json"
    except OSError:
        return Path(tempfile.gettempdir()) / "nexus-genome.json"


def load(path: Optional[Path] = None) -> GenomeV2:
    """Read the genome from disk; any problem degrades to an empty genome.

    A missing file is the normal first-run case, so it is not an error.  A
    truncated/corrupt file must not crash the gateway either — returning a fresh
    genome loses history but keeps the service up.
    """
    target = Path(path) if path is not None else default_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return GenomeV2()
    try:
        payload: Any = json.loads(raw)
    except (ValueError, TypeError):
        return GenomeV2()
    if not isinstance(payload, Mapping):
        return GenomeV2()
    try:
        return GenomeV2.from_dict(payload)
    except Exception:  # pragma: no cover - from_dict is already tolerant
        return GenomeV2()


def save(genome: GenomeV2, path: Optional[Path] = None) -> bool:
    """Atomically write the genome; returns ``True`` on success, never raises.

    The write goes to a sibling temp file which then replaces the target, so a
    crash mid-write can never leave a half-written genome behind.
    """
    target = Path(path) if path is not None else default_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(genome.to_dict(), ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".genome-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except Exception:
        return False


def install(
    agent_ids: Iterable[str] = (),
    path: Optional[Path] = None,
    *,
    genome: Optional[GenomeV2] = None,
) -> GenomeV2:
    """Adopt the saved genome, seed the roster, and auto-save from now on.

    The shared instance keeps its **identity**: the council engine, the field
    loop and the gateway each hold a reference to the one process-wide genome,
    so it is restored in place (``adopt``) instead of being swapped for a fresh
    object — a swap would leave the other holders pointing at an empty copy.

    Pass ``genome=`` to operate on a throwaway instance (tests): the process-wide
    singleton and its persistence hook are then left untouched.
    """
    target = Path(path) if path is not None else default_path()
    shared = genome if genome is not None else get_genome_v2()
    shared.adopt(load(target))
    for agent_id in agent_ids:
        key = str(agent_id or "").strip()
        if key:
            shared.ensure(key)
    if genome is None:
        set_genome_v2(shared)

        def _autosave(changed: GenomeV2) -> None:
            save(changed, target)

        set_persistence_hook(_autosave)
    save(shared, target)
    return shared
