"""
HiveLoop-X Self-Eval Tracker
=============================
يتوافق مع Schema الموجود في hive/data/self_eval.db

Schema:
    evaluations(
        id, agent_id, agent_type, task_id,
        precision, confidence, duration, success, notes, at
    )

Non-blocking: أي فشل يُسجَّل في logger فقط.
"""
from __future__ import annotations
import logging, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
# اكتشف جذر المشروع بذكاء (يدعم CI + محلي):
_candidate = (
    os.getenv("NOVAMIND_HOME")
    or os.getenv("HIVE_ROOT")
    or str(Path(__file__).resolve().parents[2])
)
ROOT = Path(_candidate)
DB_PATH = ROOT / "hive" / "data" / "self_eval.db"


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=5.0)
    try:
        # Ensure schema exists (idempotent)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT NOT NULL,
                agent_type  TEXT DEFAULT 'unknown',
                task_id     TEXT NOT NULL,
                precision   REAL DEFAULT 0.0,
                confidence  REAL DEFAULT 0.0,
                duration    INTEGER DEFAULT 0,
                success     INTEGER DEFAULT 1,
                notes       TEXT DEFAULT '',
                at          TEXT NOT NULL
            )
            """
        )
        yield con
        con.commit()
    finally:
        con.close()


def record_eval(
    agent_id: str,
    agent_type: str = "unknown",
    task_id: Optional[str] = None,
    precision: float = 0.0,
    confidence: float = 0.0,
    duration_ms: int = 0,
    success: bool = True,
    notes: Optional[str] = None,
) -> None:
    """يسجّل تقييم ذاتي — non-blocking."""
    try:
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not task_id:
            task_id = f"anon-{at}"
        if not notes:
            notes = ""

        with _conn() as con:
            con.execute(
                "INSERT INTO evaluations "
                "(agent_id, agent_type, task_id, precision, confidence,"
                " duration, success, notes, at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    agent_id or "unknown",
                    agent_type or "unknown",
                    task_id,
                    float(precision or 0.0),
                    float(confidence or 0.0),
                    int(duration_ms or 0),
                    1 if success else 0,
                    notes,
                    at,
                ),
            )
    except Exception as e:
        logger.warning(f"eval_tracker.record_eval failed: {e}")


def get_total_evals() -> dict:
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT COUNT(*), AVG(precision), AVG(confidence),"
                " SUM(CASE WHEN success=0 THEN 1 ELSE 0 END)"
                " FROM evaluations"
            ).fetchone()
        return {
            "evals": row[0] or 0,
            "avg_precision": round(row[1] or 0.0, 3),
            "avg_confidence": round(row[2] or 0.0, 3),
            "failures": row[3] or 0,
        }
    except Exception as e:
        logger.warning(f"get_total_evals failed: {e}")
        return {"evals": 0, "avg_precision": 0.0, "avg_confidence": 0.0, "failures": 0}


def get_agent_stats() -> list:
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT agent_id, COUNT(*), AVG(precision), AVG(confidence),"
                " AVG(duration), SUM(CASE WHEN success=0 THEN 1 ELSE 0 END)"
                " FROM evaluations GROUP BY agent_id ORDER BY COUNT(*) DESC"
            ).fetchall()
        return [
            {
                "agent_id": r[0],
                "evals": r[1] or 0,
                "avg_precision": round(r[2] or 0.0, 3),
                "avg_confidence": round(r[3] or 0.0, 3),
                "avg_duration_ms": int(r[4] or 0),
                "failures": r[5] or 0,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"get_agent_stats failed: {e}")
        return []


def reset() -> None:
    try:
        with _conn() as con:
            con.execute("DELETE FROM evaluations")
    except Exception as e:
        logger.warning(f"eval_tracker.reset failed: {e}")


# ═══════════════════════════════════════════════════════
#  Wrapper للبوت — get_evals
# ═══════════════════════════════════════════════════════

def get_evals(limit: int = 20) -> list:
    """يرجع آخر N تقييم من self_eval.db — للاستخدام في البوت.
    
    Returns:
        list of dicts: [{id, agent_id, precision, confidence, success, at}, ...]
    """
    try:
        with _conn() as con:
            cur = con.execute(
                """
                SELECT id, agent_id, agent_type,
                       precision, confidence, success, at
                FROM evaluations
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "agent_id": r[1] or "?",
                    "agent_type": r[2] or "?",
                    "precision": r[3] or 0.0,
                    "confidence": r[4] or 0.0,
                    "success": bool(r[5]),
                    "at": r[6] or "?",
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning(f"get_evals failed: {e}")
        return []
