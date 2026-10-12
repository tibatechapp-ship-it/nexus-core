#!/usr/bin/env python3
"""HiveLoop Task Memory — SQLite-based task store"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.memory.task_memory")

ROOT = Path(__file__).resolve().parent.parent.parent
DB_DIR = ROOT / "hive" / "data"
DB_PATH = DB_DIR / "tasks.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    task_type TEXT,
    objective TEXT,
    status TEXT NOT NULL,
    duration_seconds REAL,
    output TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent ON tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_created ON tasks(created_at);


CREATE TABLE IF NOT EXISTS agent_stats (
    agent_id TEXT PRIMARY KEY,
    total_runs INTEGER DEFAULT 0,
    successes INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0,
    total_duration REAL DEFAULT 0.0,
    last_run TEXT
);
"""


class TaskMemory:
    """ذاكرة المهام — SQLite"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def save(self, result) -> bool:
        """احفظ نتيجة مهمة."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tasks (task_id, agent_id, task_type, objective, status, duration_seconds, output, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.task_id,
                        result.agent_id,
                        getattr(result, "task_type", None),
                        getattr(result, "objective", None),
                        result.status,
                        result.duration_seconds,
                        json.dumps(result.output, default=str)[:10000] if result.output else None,
                        result.error,
                        result.finished_at or datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.execute(
                    """INSERT INTO agent_stats (agent_id, total_runs, successes, failures, total_duration, last_run)
                       VALUES (?, 1, ?, ?, ?, ?)
                       ON CONFLICT(agent_id) DO UPDATE SET
                           total_runs = total_runs + 1,
                           successes = successes + ?,
                           failures = failures + ?,
                           total_duration = total_duration + ?,
                           last_run = ?""",
                    (
                        result.agent_id,
                        1 if result.status == "success" else 0,
                        1 if result.status != "success" else 0,
                        result.duration_seconds,
                        result.finished_at,
                        1 if result.status == "success" else 0,
                        1 if result.status != "success" else 0,
                        result.duration_seconds,
                        result.finished_at,
                    ),
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"save failed: {e}")
            return False

    def get(self, task_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def recent(self, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def by_agent(self, agent_id: str, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM tasks WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?", (agent_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def agent_stats(self) -> List[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM agent_stats ORDER BY total_runs DESC").fetchall()
            return [dict(r) for r in rows]

    def summary(self) -> Dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            successes = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'success'").fetchone()[0]
            failures = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'success'").fetchone()[0]
            avg_dur = conn.execute("SELECT AVG(duration_seconds) FROM tasks").fetchone()[0] or 0.0
            agents = conn.execute("SELECT COUNT(*) FROM agent_stats").fetchone()[0]
        return {
            "total_tasks": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total, 3) if total else 0.0,
            "avg_duration": round(avg_dur, 3),
            "agents_seen": agents,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    print("Testing TaskMemory...")
    mem = TaskMemory()
    print("Summary:", mem.summary())
    print("OK")
