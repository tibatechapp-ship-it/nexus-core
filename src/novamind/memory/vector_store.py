"""Vector store — numpy + sqlite."""
import json, logging, os, sqlite3, threading
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np

logger = logging.getLogger("VectorStore")
ROOT = Path(os.getenv("HIVE_ROOT", "/public"))
DB_PATH = ROOT / "hive" / "data" / "vectors.db"

class VectorStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
    def _init_db(self):
        with self._conn() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT, namespace TEXT NOT NULL,
                text TEXT NOT NULL, embedding BLOB NOT NULL,
                meta TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ns ON vectors(namespace)")
    def _conn(self):
        return sqlite3.connect(str(self.db_path), timeout=5.0)
    def add(self, namespace, text, embedding, meta=None):
        if not embedding: return -1
        arr = np.asarray(embedding, dtype=np.float32)
        with self._lock, self._conn() as con:
            cur = con.execute("INSERT INTO vectors(namespace,text,embedding,meta) VALUES (?,?,?,?)",
                (namespace, text[:8000], arr.tobytes(), json.dumps(meta or {}, ensure_ascii=False)))
            return cur.lastrowid
    def search(self, namespace, query_emb, top_k=5):
        if not query_emb: return []
        q = np.asarray(query_emb, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-9)
        with self._conn() as con:
            rows = con.execute("SELECT id,text,embedding,meta,at FROM vectors WHERE namespace=?",
                (namespace,)).fetchall()
        if not rows: return []
        results = []
        for row in rows:
            try:
                v = np.frombuffer(row[2], dtype=np.float32)
                v_norm = v / (np.linalg.norm(v) + 1e-9)
                score = float(np.dot(q_norm, v_norm))
                results.append({"id":row[0],"text":row[1],"meta":json.loads(row[3] or "{}"),
                    "at":row[4],"score":round(score,4)})
            except Exception as e:
                logger.warning(f"row: {e}")
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    def count(self, namespace=None):
        with self._conn() as con:
            r = con.execute("SELECT COUNT(*) FROM vectors WHERE namespace=?" if namespace
                else "SELECT COUNT(*) FROM vectors", (namespace,) if namespace else ()).fetchone()
            return r[0] if r else 0
    def delete_namespace(self, namespace):
        with self._lock, self._conn() as con:
            cur = con.execute("DELETE FROM vectors WHERE namespace=?", (namespace,))
            return cur.rowcount
    def namespaces(self):
        with self._conn() as con:
            return [r[0] for r in con.execute("SELECT DISTINCT namespace FROM vectors").fetchall()]

_store = None
def get_store():
    global _store
    if _store is None: _store = VectorStore()
    return _store
