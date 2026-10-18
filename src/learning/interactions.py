"""Long-term interaction memory — every chat becomes recallable experience.

Phase 1 of the five-axis plan (الذاكرة طويلة المدى + التقييم الذاتي):
:class:`InteractionStore` persists each real ``/api/chat`` exchange (question,
answer, self-rating, retry, outcome) in a small SQLite table, and
:meth:`InteractionStore.similar` ranks past interactions against a new
question so the gateway can fold them into the system prompt.

Design notes (mirrors :mod:`src.novamind.core.session_store` conventions):

* path resolution ``$NEXUS_INTERACTIONS_DB`` → ``$NEXUS_DB`` sibling
  ``interactions.db`` → ``<repo>/data/interactions.db``;
* one connection + ``RLock`` (writes are rare, reads are one per chat);
* tokenisation delegates to :func:`src.knowledge.base.tokenize` (Arabic-aware
  normalisation) after stripping Arabic punctuation, so Arabic questions
  actually match;
* ``similar()`` only ever returns *successful* answers (``signal_ok=1``) — a
  failed reply is history, not guidance;
* nothing here calls an LLM: pure stdlib + sqlite3, fully offline-testable.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import RLock
from typing import Any

from src.knowledge.base import tokenize as _tokenize
from src.memory.base import connect

__all__ = [
    "InteractionStore",
    "default_interaction_db_path",
    "get_interaction_store",
    "reset_interaction_store",
]

#: Schema version written to ``PRAGMA user_version``.
_SCHEMA_VERSION = 1

#: Default number of past interactions recalled into a prompt.
_DEFAULT_K = 3

#: Arabic + ASCII punctuation stripped before tokenising (``tokenize`` keeps
#: ``؟`` inside words because it sits inside the Arabic Unicode block).
_STRIP = str.maketrans({c: " " for c in "؟،؛!\"'()[]{}«»…ـ/\\|<>*&%$#@+=~`,."})


def default_interaction_db_path() -> str:
    """Where the interaction database lives (env chain, one winner)."""
    env = os.environ.get("NEXUS_INTERACTIONS_DB")
    if env:
        return env
    base = os.environ.get("NEXUS_DB")
    if base:
        return str(Path(base).with_name("interactions.db"))
    return str(Path(__file__).resolve().parents[2] / "data" / "interactions.db")


def _tokens(text: str) -> set[str]:
    """Arabic-aware token set of ``text`` (empty for tokenless input)."""
    return set(_tokenize((text or "").translate(_STRIP)))


class InteractionStore:
    """SQLite-backed store of chat interactions + similarity recall."""

    def __init__(
        self,
        db_path: str | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = str(db_path) if db_path else default_interaction_db_path()
        self._clock = clock
        self._lock = RLock()
        self._conn = connect(self.path)
        self._init_schema()

    # -- schema ------------------------------------------------------------
    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    signal_ok INTEGER NOT NULL,
                    self_rating TEXT,
                    reflection_reason TEXT,
                    retry_used INTEGER NOT NULL DEFAULT 0,
                    retried_rating TEXT,
                    awareness_gap INTEGER,
                    lesson TEXT,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_interactions_agent
                    ON interactions(agent_id, created_at DESC);
                """
            )
            # PRAGMA does not accept bound parameters (sqlite3 syntax error);
            # _SCHEMA_VERSION is a module int constant — same pattern as
            # novamind.core.session_store.
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self._conn.commit()

    # -- write -------------------------------------------------------------
    def save(
        self,
        *,
        agent_id: str,
        question: str,
        answer: str,
        signal_ok: bool,
        self_rating: str | None = None,
        reflection_reason: str | None = None,
        retry_used: bool = False,
        retried_rating: str | None = None,
        awareness_gap: int | None = None,
        lesson: str | None = None,
    ) -> int:
        """Persist one interaction and return its row id."""
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO interactions (
                    agent_id, question, answer, signal_ok, self_rating,
                    reflection_reason, retry_used, retried_rating,
                    awareness_gap, lesson, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id or "default",
                    question or "",
                    answer or "",
                    1 if signal_ok else 0,
                    self_rating,
                    reflection_reason,
                    1 if retry_used else 0,
                    retried_rating,
                    awareness_gap,
                    lesson,
                    float(self._clock()),
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)

    # -- read --------------------------------------------------------------
    def _rows(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params)]

    def similar(
        self, question: str, k: int = _DEFAULT_K, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Top-``k`` past *successful* interactions covering ``question``.

        Score = fraction of the new question's tokens the past question
        contains (query-coverage), ties broken by recency.  An empty/tokenless
        question or zero overlaps returns ``[]``.
        """
        query_tokens = _tokens(question)
        if not query_tokens:
            return []
        sql = (
            "SELECT * FROM interactions WHERE signal_ok = 1 "
            "AND answer != ''"
        )
        params: list[Any] = []
        if agent_id:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY created_at DESC"
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in self._rows(sql, params):
            overlap = len(query_tokens & _tokens(str(row.get("question") or "")))
            if overlap:
                ranked.append((overlap / len(query_tokens), row))
        ranked.sort(key=lambda item: (-item[0], -float(item[1]["created_at"])))
        return [
            {**row, "score": round(score, 3)}
            for score, row in ranked[: max(0, int(k))]
        ]

    def recent(
        self, limit: int = 20, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Newest-first interactions (``limit`` clamped to 1..200)."""
        lim = max(1, min(int(limit or 20), 200))
        sql = "SELECT * FROM interactions"
        params: list[Any] = []
        if agent_id:
            sql += " WHERE agent_id = ?"
            params.append(agent_id)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(lim)
        return self._rows(sql, params)

    def count(self) -> int:
        """Total stored interactions."""
        rows = self._rows("SELECT COUNT(*) AS n FROM interactions")
        return int(rows[0]["n"])

    def stats(self) -> dict[str, Any]:
        """Aggregate health of the memory (counts per rating + gaps)."""
        rows = self._rows(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN self_rating = 'excellent' THEN 1 ELSE 0 END) AS excellent,
                SUM(CASE WHEN self_rating = 'good' THEN 1 ELSE 0 END) AS good,
                SUM(CASE WHEN self_rating = 'poor' THEN 1 ELSE 0 END) AS poor,
                SUM(CASE WHEN self_rating IS NULL THEN 1 ELSE 0 END) AS unrated,
                SUM(retry_used) AS retries,
                SUM(CASE WHEN awareness_gap = 1 THEN 1 ELSE 0 END) AS gaps
            FROM interactions
            """
        )
        row = rows[0]
        return {
            "count": int(row["total"] or 0),
            "by_rating": {
                "excellent": int(row["excellent"] or 0),
                "good": int(row["good"] or 0),
                "poor": int(row["poor"] or 0),
                "unrated": int(row["unrated"] or 0),
            },
            "retries": int(row["retries"] or 0),
            "awareness_gaps": int(row["gaps"] or 0),
        }


_STORE: InteractionStore | None = None


def get_interaction_store(
    db_path: str | None = None,
) -> InteractionStore:
    """Process-wide singleton (idempotent; first path wins)."""
    global _STORE
    if _STORE is None:
        _STORE = InteractionStore(db_path)
    return _STORE


def reset_interaction_store() -> None:
    """Drop the singleton (tests / deliberate re-open)."""
    global _STORE
    _STORE = None
