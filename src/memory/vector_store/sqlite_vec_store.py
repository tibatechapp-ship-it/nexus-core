"""SQLite-vec implementation of VectorStore."""
from __future__ import annotations
import json
import os
import sqlite3
import struct
from typing import Sequence

from .base import VectorStore, SearchResult


def _embedding_to_blob(embedding: Sequence[float]) -> bytes:
    """يحوّل قائمة floats إلى bytes (float32)."""
    return struct.pack(f"{len(embedding)}f", *embedding)


class SQLiteVecStore(VectorStore):
    """تنفيذ VectorStore عبر sqlite-vec.

    يتطلب: sqlite-vec مثبت (vec0.so).
    """

    def __init__(self, path: str, dim: int = 512, table: str = "vectors"):
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
        """)
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table}_meta (
                rowid INTEGER PRIMARY KEY,
                id TEXT UNIQUE,
                text TEXT,
                metadata TEXT
            )
        """)
        self._conn.commit()

    def add(self, id: str, text: str, embedding: Sequence[float],
            metadata: dict = None) -> None:
        blob = _embedding_to_blob(embedding)
        cur = self._conn.execute(
            f"INSERT INTO {self.table}(embedding) VALUES (?)", (blob,)
        )
        rowid = cur.lastrowid
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self.table}_meta(rowid, id, text, metadata) "
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
        """, (blob, k)).fetchall()
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
            f"SELECT rowid FROM {self.table}_meta WHERE id = ?", (id,)
        ).fetchone()
        if not row:
            return False
        self._conn.execute(f"DELETE FROM {self.table} WHERE rowid = ?", (row[0],))
        self._conn.execute(f"DELETE FROM {self.table}_meta WHERE rowid = ?", (row[0],))
        self._conn.commit()
        return True

    def clear(self) -> None:
        self._conn.execute(f"DELETE FROM {self.table}")
        self._conn.execute(f"DELETE FROM {self.table}_meta")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
