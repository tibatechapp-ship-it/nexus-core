"""SQLite store for training runs and certificates (P3).

Stdlib-only and phone-safe, mirroring ``novamind.core.session_store``: WAL mode,
one connection per operation, ``PRAGMA user_version`` for migrations, and a
path resolution chain that works on Termux without configuration.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import TrainingRun

#: Bump when the schema below changes in a way older code cannot read.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_runs (
    run_id          TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    spec            TEXT NOT NULL,
    started_at      REAL NOT NULL,
    finished_at     REAL NOT NULL,
    completion_rate REAL NOT NULL,
    training_score  REAL NOT NULL,
    gate_score      REAL NOT NULL,
    final_score     REAL NOT NULL,
    verdict         TEXT NOT NULL,
    certified       INTEGER NOT NULL DEFAULT 0,
    phases          TEXT NOT NULL DEFAULT '[]',
    detail          TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_training_runs_agent
    ON training_runs (agent_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_runs_finished
    ON training_runs (finished_at DESC);

CREATE TABLE IF NOT EXISTS training_certificates (
    certificate_id  TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    spec            TEXT NOT NULL,
    score           REAL NOT NULL,
    issued_at       REAL NOT NULL,
    signature       TEXT NOT NULL DEFAULT '',
    payload         TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_training_certs_agent
    ON training_certificates (agent_id, issued_at DESC);
"""


def _repo_root() -> Path:
    """Best-effort repo root, derived from this file's location."""
    return Path(__file__).resolve().parents[3]


def default_db_path() -> Path:
    """Resolve the training DB path.

    ``$NEXUS_TRAINING_DB`` wins; then ``$NEXUS_DB`` (same folder, so a deployed
    instance keeps its data together); then ``<repo>/data``; then a temp dir
    fallback for read-only installs.
    """
    explicit = os.environ.get("NEXUS_TRAINING_DB")
    if explicit:
        return Path(explicit)
    sibling = os.environ.get("NEXUS_DB")
    if sibling:
        return Path(sibling).with_name("training.db")
    data_dir = _repo_root() / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "training.db"
    except OSError:
        return Path(tempfile.gettempdir()) / "nexus-training.db"


def _row_to_run(row: sqlite3.Row) -> TrainingRun:
    """Rebuild a :class:`TrainingRun` from a DB row."""
    return TrainingRun(
        run_id=row["run_id"],
        agent_id=row["agent_id"],
        spec=row["spec"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        completion_rate=row["completion_rate"],
        training_score=row["training_score"],
        gate_score=row["gate_score"],
        final_score=row["final_score"],
        verdict=row["verdict"],
        certified=bool(row["certified"]),
        phases=tuple(json.loads(row["phases"] or "[]")),
        detail=json.loads(row["detail"] or "{}"),
    )


class TrainingStore:
    """Persistence for training runs and the certificates they earn."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self._lock = threading.Lock()
        self._init_schema()

    # ── plumbing ─────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # ── runs ─────────────────────────────────────────────────────────────
    def save_run(self, run: TrainingRun) -> TrainingRun:
        """Insert or replace one run."""
        payload = (
            run.run_id, run.agent_id, run.spec, run.started_at, run.finished_at,
            run.completion_rate, run.training_score, run.gate_score,
            run.final_score, run.verdict, int(run.certified),
            json.dumps([dict(p) for p in run.phases], ensure_ascii=False),
            json.dumps(run.detail, ensure_ascii=False),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO training_runs ("
                " run_id, agent_id, spec, started_at, finished_at,"
                " completion_rate, training_score, gate_score, final_score,"
                " verdict, certified, phases, detail"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                payload,
            )
        return run

    def get_run(self, run_id: str) -> Optional[TrainingRun]:
        """One run by id, or ``None``."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM training_runs WHERE run_id=?", (str(run_id),)
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def list_runs(
        self, *, agent_id: Optional[str] = None, limit: int = 50
    ) -> List[TrainingRun]:
        """Most recent runs first, optionally filtered by agent."""
        bounded = max(1, min(int(limit), 500))
        with self._connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM training_runs WHERE agent_id=?"
                    " ORDER BY finished_at DESC LIMIT ?",
                    (str(agent_id), bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM training_runs ORDER BY finished_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [_row_to_run(r) for r in rows]

    def latest_run(self, agent_id: str) -> Optional[TrainingRun]:
        """The agent's newest run, or ``None`` if it never trained."""
        runs = self.list_runs(agent_id=agent_id, limit=1)
        return runs[0] if runs else None

    # ── certificates ─────────────────────────────────────────────────────
    def issue_certificate(
        self, *, certificate_id: str, run: TrainingRun,
        signature: str = "", payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a graduation certificate for ``run``."""
        record = {
            "certificate_id": str(certificate_id),
            "run_id": run.run_id,
            "agent_id": run.agent_id,
            "spec": run.spec,
            "score": float(run.final_score),
            "issued_at": float(run.finished_at),
            "signature": str(signature),
            "payload": dict(payload or {}),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO training_certificates ("
                " certificate_id, run_id, agent_id, spec, score, issued_at,"
                " signature, payload"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    record["certificate_id"], record["run_id"], record["agent_id"],
                    record["spec"], record["score"], record["issued_at"],
                    record["signature"],
                    json.dumps(record["payload"], ensure_ascii=False),
                ),
            )
        return record

    def list_certificates(
        self, *, agent_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Certificates, newest first."""
        bounded = max(1, min(int(limit), 500))
        with self._connect() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT * FROM training_certificates WHERE agent_id=?"
                    " ORDER BY issued_at DESC LIMIT ?",
                    (str(agent_id), bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM training_certificates"
                    " ORDER BY issued_at DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [
            {
                "certificate_id": r["certificate_id"],
                "run_id": r["run_id"],
                "agent_id": r["agent_id"],
                "spec": r["spec"],
                "score": r["score"],
                "issued_at": r["issued_at"],
                "signature": r["signature"],
                "payload": json.loads(r["payload"] or "{}"),
            }
            for r in rows
        ]

    # ── aggregate ────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        """Counts and rates across every stored run and certificate."""
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT COUNT(*) AS total,"
                " SUM(certified) AS certified,"
                " AVG(final_score) AS avg_score"
                " FROM training_runs"
            ).fetchone()
            cert_total = conn.execute(
                "SELECT COUNT(*) AS c FROM training_certificates"
            ).fetchone()["c"]
            agent_total = conn.execute(
                "SELECT COUNT(DISTINCT agent_id) AS c FROM training_runs"
            ).fetchone()["c"]
        total = int(run_row["total"] or 0)
        certified = int(run_row["certified"] or 0)
        return {
            "runs": total,
            "certified": certified,
            "agents_trained": int(agent_total or 0),
            "certificates": int(cert_total or 0),
            "avg_score": round(float(run_row["avg_score"] or 0.0), 4),
            "certification_rate": round(certified / total, 4) if total else 0.0,
            "schema_version": SCHEMA_VERSION,
            "path": str(self.path),
        }


_STORE: Optional[TrainingStore] = None
_STORE_LOCK = threading.Lock()


def get_store(path: Optional[Path] = None) -> TrainingStore:
    """Process-wide training store (pass ``path`` in tests)."""
    global _STORE
    if path is not None:
        return TrainingStore(path)
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = TrainingStore()
        return _STORE


def reset_store() -> None:
    """Drop the cached singleton (tests only)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = None


def now() -> float:
    """Indirection so tests can reason about timestamps."""
    return time.time()
