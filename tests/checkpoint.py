"""Resumable runs — checkpoint the stages a pattern has already finished.

A long pipeline can be interrupted (a crash, a timeout, a phone that sleeps)
half-way through. Re-running it from scratch pays for the stages that already
succeeded. This module records each finished stage so a later run with the same
``run_id`` can skip the successful ones and continue from where it stopped.

* :class:`StageCheckpoint` — one finished stage (agent, ok, output, timing).
* :class:`CheckpointStore` — a thread-safe, keyed-by-``(run_id, stage)`` store;
  in-memory by default, or persisted to a JSON file when a path is given.

Resumption is **opt-in and lossless**: with no :class:`CheckpointStore` the
pattern behaves exactly as before. Only stages that **succeeded** are skipped on
resume — a failed stage is retried, so a transient failure never gets frozen in.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["CheckpointStore", "StageCheckpoint"]


@dataclass(frozen=True, slots=True)
class StageCheckpoint:
    """The recorded outcome of one finished stage of a pattern run."""

    run_id: str
    stage: int
    agent: str
    ok: bool
    output: str = ""
    error: str | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "agent": self.agent,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageCheckpoint:
        """Rebuild a checkpoint from :meth:`to_dict` output (tolerant of gaps)."""
        return cls(
            run_id=str(data.get("run_id", "")),
            stage=int(data.get("stage", 0)),
            agent=str(data.get("agent", "")),
            ok=bool(data.get("ok", False)),
            output=str(data.get("output", "")),
            error=None if data.get("error") is None else str(data["error"]),
            duration_s=float(data.get("duration_s", 0.0)),
        )


class CheckpointStore:
    """A thread-safe record of finished stages, keyed by ``(run_id, stage)``.

    Pass ``path`` to persist across processes (a JSON file); omit it for an
    in-memory store (the default, used by tests). Reading a corrupt file never
    raises — the store simply starts empty.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        #: run_id -> {stage index -> checkpoint}
        self._stages: dict[str, dict[int, StageCheckpoint]] = {}
        if self._path is not None and self._path.exists():
            self._load()

    # -- writes ------------------------------------------------------------
    def save(self, checkpoint: StageCheckpoint) -> None:
        """Record (or overwrite) one stage's checkpoint."""
        with self._lock:
            self._stages.setdefault(checkpoint.run_id, {})[checkpoint.stage] = checkpoint
            self._flush_locked()

    def clear(self, run_id: str) -> int:
        """Forget every checkpoint for ``run_id``; return how many were removed."""
        with self._lock:
            removed = len(self._stages.pop(run_id, {}))
            if removed:
                self._flush_locked()
            return removed

    # -- reads -------------------------------------------------------------
    def stage(self, run_id: str, stage: int) -> StageCheckpoint | None:
        """Return the checkpoint for ``(run_id, stage)`` if recorded."""
        with self._lock:
            return self._stages.get(run_id, {}).get(stage)

    def completed_stage(self, run_id: str, stage: int) -> StageCheckpoint | None:
        """Return the checkpoint only if that stage **succeeded** (else ``None``).

        A failed stage returns ``None`` so a resumed run retries it instead of
        freezing the failure in.
        """
        checkpoint = self.stage(run_id, stage)
        if checkpoint is not None and checkpoint.ok:
            return checkpoint
        return None

    def stages(self, run_id: str) -> dict[int, StageCheckpoint]:
        """Return a copy of every recorded stage for ``run_id``."""
        with self._lock:
            return dict(self._stages.get(run_id, {}))

    def runs(self) -> list[str]:
        """Return the run ids with at least one checkpoint (sorted)."""
        with self._lock:
            return sorted(self._stages)

    def __len__(self) -> int:
        """Total number of checkpoints across every run."""
        with self._lock:
            return sum(len(stages) for stages in self._stages.values())

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        assert self._path is not None  # guarded by the constructor
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        loaded: dict[str, dict[int, StageCheckpoint]] = {}
        for run_id, stages in raw.items():
            if not isinstance(stages, dict):
                continue
            bucket: dict[int, StageCheckpoint] = {}
            for stage_key, payload in stages.items():
                if not isinstance(payload, dict):
                    continue
                try:
                    checkpoint = StageCheckpoint.from_dict(payload)
                except (TypeError, ValueError):  # pragma: no cover - malformed row
                    continue
                bucket[int(stage_key)] = checkpoint
            if bucket:  # only keep runs that actually hold a checkpoint
                loaded[str(run_id)] = bucket
        self._stages = loaded

    def _flush_locked(self) -> None:
        """Write the whole store to disk (caller holds the lock)."""
        if self._path is None:
            return
        payload: dict[str, dict[str, Any]] = {
            run_id: {str(stage): cp.to_dict() for stage, cp in stages.items()}
            for run_id, stages in self._stages.items()
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)
