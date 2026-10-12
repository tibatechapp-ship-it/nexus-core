"""
HiveLoop-X Cost Tracker
========================
يتوافق مع Schema الموجود في hive/data/costs.db

Schema:
    costs(
        id, task_id, agent_id, provider, model,
        prompt_tokens, completion_tokens, total_tokens,
        cost_usd, duration, success, at
    )

Non-blocking: أي فشل يُسجَّل في logger فقط.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
#  المسارات
# ─────────────────────────────────────────────────────
# اكتشف جذر المشروع بذكاء (يدعم CI + محلي):
# 1. NOVAMIND_HOME (يُعرّفه GitHub Actions)
# 2. HIVE_ROOT (للتوافق مع الإصدارات القديمة)
# 3. مسار نسبي من الملف (احتياطي آمن)
_candidate = (
    os.getenv("NOVAMIND_HOME")
    or os.getenv("HIVE_ROOT")
    or str(Path(__file__).resolve().parents[2])
)
ROOT = Path(_candidate)
DB_PATH = ROOT / "src" / "novamind" / "core" / "hive" / "data" / "costs.db"

# ─────────────────────────────────────────────────────
#  أسعار تقريبية لكل 1000 tokens (USD)
# ─────────────────────────────────────────────────────
PRICES_PER_1K_TOKENS = {
    "groq": 0.0,
    "glm": 0.001,
    "zhipu": 0.001,
    "mistral": 0.002,
    "gemini": 0.0005,
    "openrouter": 0.0015,
    "default": 0.001,
}


def _price_for(provider: str) -> float:
    if not provider:
        return PRICES_PER_1K_TOKENS["default"]
    p = provider.lower()
    for prefix, price in PRICES_PER_1K_TOKENS.items():
        if prefix != "default" and p.startswith(prefix):
            return price
    return PRICES_PER_1K_TOKENS["default"]


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=5.0)
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ─────────────────────────────────────────────────────
#  Public API — متوافق مع Schema الموجود
# ─────────────────────────────────────────────────────
def record_cost(
    provider: str,
    tokens: int = 0,
    duration_ms: int = 0,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    success: bool = True,
    error: Optional[str] = None,
    model: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
) -> None:
    """يسجّل استدعاء واحد. Non-blocking."""
    try:
        price = _price_for(provider)
        total_tokens = int(tokens or 0)
        cost = (total_tokens / 1000.0) * price
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # إذا prompt_tokens/completion_tokens مش محددين، احسبهم تقريبياً
        if prompt_tokens is None and completion_tokens is None:
            prompt_tokens = 0
            completion_tokens = total_tokens
        else:
            prompt_tokens = int(prompt_tokens or 0)
            completion_tokens = int(completion_tokens or 0)

        # الحقول NOT NULL في Schema:
        #   - task_id NOT NULL
        #   - at NOT NULL
        # نضمن دايماً قيم صالحة
        if not task_id:
            task_id = f"anon-{at}"
        if not agent_id:
            agent_id = "unknown"
        if not model:
            model = provider or "unknown"
        if not at:
            at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with _conn() as con:
            con.execute(
                """
                INSERT INTO costs
                    (task_id, agent_id, provider, model,
                     prompt_tokens, completion_tokens, total_tokens,
                     cost_usd, duration, success, at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    agent_id,
                    provider or "unknown",
                    model or provider,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    float(cost),
                    int(duration_ms or 0),
                    1 if success else 0,
                    at,
                ),
            )
    except Exception as e:
        logger.warning(f"cost_tracker.record_cost failed: {e}")


def get_total_cost() -> dict:
    """إجمالي التكاليف عبر كل التاريخ."""
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT COUNT(*), SUM(total_tokens), SUM(cost_usd), "
                "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) FROM costs"
            ).fetchone()
        return {
            "calls": row[0] or 0,
            "tokens": row[1] or 0,
            "cost_usd": round(row[2] or 0.0, 6),
            "failures": row[3] or 0,
        }
    except Exception as e:
        logger.warning(f"cost_tracker.get_total_cost failed: {e}")
        return {"calls": 0, "tokens": 0, "cost_usd": 0.0, "failures": 0}


def get_provider_stats() -> list:
    """إحصاءات لكل مزود."""
    try:
        with _conn() as con:
            rows = con.execute(
                """
                SELECT provider,
                       COUNT(*)          AS calls,
                       SUM(total_tokens) AS tokens,
                       SUM(cost_usd)     AS cost,
                       AVG(duration)     AS avg_ms,
                       SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failures
                FROM costs
                GROUP BY provider
                ORDER BY calls DESC
                """
            ).fetchall()
        return [
            {
                "provider": r[0],
                "calls": r[1] or 0,
                "tokens": r[2] or 0,
                "cost_usd": round(r[3] or 0.0, 6),
                "avg_duration_ms": int(r[4] or 0),
                "failures": r[5] or 0,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"cost_tracker.get_provider_stats failed: {e}")
        return []


def get_daily_cost(date: Optional[str] = None) -> dict:
    """تكاليف يوم محدد (YYYY-MM-DD) أو اليوم الحالي."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT COUNT(*), SUM(total_tokens), SUM(cost_usd) "
                "FROM costs WHERE at LIKE ?",
                (f"{date}%",),
            ).fetchone()
        return {
            "date": date,
            "calls": row[0] or 0,
            "tokens": row[1] or 0,
            "cost_usd": round(row[2] or 0.0, 6),
        }
    except Exception as e:
        logger.warning(f"cost_tracker.get_daily_cost failed: {e}")
        return {"date": date, "calls": 0, "tokens": 0, "cost_usd": 0.0}


def reset():
    """ينشئ/يعيد إنشاء الجدول."""
    with _conn() as con:
        con.execute("DROP TABLE IF EXISTS costs")
        con.execute("""
            CREATE TABLE costs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                agent_id TEXT,
                provider TEXT,
                model TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                duration INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def get_costs(limit: int = 20) -> list:
    """يرجع آخر N تكلفة من costs.db — للاستخدام في البوت.
    
    Returns:
        list of dicts: [{id, provider, model, tokens, cost, at}, ...]
    """
    try:
        with _conn() as con:
            cur = con.execute(
                """
                SELECT id, provider, model,
                       prompt_tokens + completion_tokens as tokens,
                       cost_usd, at
                FROM costs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "provider": r[1] or "?",
                    "model": r[2] or "?",
                    "tokens": r[3] or 0,
                    "cost_usd": r[4] or 0.0,
                    "at": r[5] or "?",
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning(f"get_costs failed: {e}")
        return []
