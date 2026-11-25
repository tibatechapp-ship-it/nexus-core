"""SQLite-vec implementation of VectorStore."""
from __future__ import annotations
import json
import os
import re
import sqlite3
import struct
from typing import Sequence, Any

from .base import VectorStore, SearchResult


def _embedding_to_blob(embedding: Sequence[float]) -> bytes:
    """يحوّل قائمة floats إلى bytes (float32)."""
    return struct.pack(f"{len(embedding)}f", *embedding)


class SQLiteVecStore(VectorStore):
    """تنفيذ VectorStore عبر sqlite-vec.

    يتطلب: sqlite-vec مثبت (vec0.so).
    """

    def __init__(self: Any, path: str, dim: int = 512, table: str = "vectors") -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", table):
            raise ValueError("unsafe SQLite vector table identifier")
        if not isinstance(dim, int) or not 1 <= dim <= 4096:
            raise ValueError("vector dimension must be an integer from 1 to 4096")
        self.path = path
        self.dim = dim
        self.table = table
        # أنشئ المجلد الأب تلقائياً
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.enable_load_extension(True)
        self._load_vec()
        self._init_schema()

    def _load_vec(self) -> None:
        """يحمّل امتداد sqlite-vec."""
        candidates = [
            "vec0",
            "vec0.so",
            "/data/data/com.termux/files/usr/lib/python3.14/site-packages/vec0.so",
        ]
        for c in candidates:
            try:
                self._conn.load_extension(c)
                return
            except Exception:
                continue
        raise RuntimeError("sqlite-vec غير مثبت")

    def _init_schema(self) -> None:
        self._conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {self.table}
            USING vec0(embedding float[{self.dim}])
        """)  # nosec B608 — table identifier and dimension validated in __init__
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table}_meta (
                rowid INTEGER PRIMARY KEY,
                id TEXT UNIQUE,
                text TEXT,
                metadata TEXT
            )
        """)  # nosec B608 — table identifier validated in __init__
        self._conn.commit()

    def add(self, id: str, text: str, embedding: Sequence[float],
            metadata: dict | None = None) -> None:
        blob = _embedding_to_blob(embedding)
        cur = self._conn.execute(
            f"INSERT INTO {self.table}(embedding) VALUES (?)", (blob,)  # nosec B608 — table identifier validated in __init__
        )
        rowid = cur.lastrowid
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self.table}_meta(rowid, id, text, metadata) "  # nosec B608 — table identifier validated in __init__
            f"VALUES (?, ?, ?, ?)",
            (rowid, id, text, json.dumps(metadata or {})),
        )
        self._conn.commit()

    def search(self, embedding: Sequence[float], k: int = 5) -> list[SearchResult]:
        blob = _embedding_to_blob(embedding)
        rows = self._conn.execute(f"""
            SELECT v.rowid, v.distance, m.id, m.text, m.metadata
            FROM {self.table} v
            JOIN {self.table}_meta m ON m.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
        """, (blob, k)).fetchall()  # nosec B608 — table identifier validated in __init__
        return [
            SearchResult(
                id=r[2], text=r[3],
                distance=r[1],
                metadata=json.loads(r[4] or "{}"),
            )
            for r in rows
        ]

    def delete(self, id: str) -> bool:
        row = self._conn.execute(
            f"SELECT rowid FROM {self.table}_meta WHERE id = ?",  # nosec B608 — table identifier validated in __init__
            (id,)
        ).fetchone()
        if not row:
            return False
        self._conn.execute(f"DELETE FROM {self.table} WHERE rowid = ?", (row[0],))  # nosec B608 — table identifier validated in __init__
        self._conn.execute(f"DELETE FROM {self.table}_meta WHERE rowid = ?", (row[0],))  # nosec B608 — table identifier validated in __init__
        self._conn.commit()
        return True

    def clear(self) -> None:
        self._conn.execute(f"DELETE FROM {self.table}")  # nosec B608 — table identifier validated in __init__
        self._conn.execute(f"DELETE FROM {self.table}_meta")  # nosec B608 — table identifier validated in __init__
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
