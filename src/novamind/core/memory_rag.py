"""Simple RAG - استرجاع الدروس السابقة."""
import sqlite3
import logging
import time
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger("RAG")

class SimpleRAG:
    def __init__(self, db_path: str = "data/company/rag_memory.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specialty TEXT,
                    task TEXT,
                    response TEXT,
                    success INTEGER,
                    timestamp REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_spec ON lessons(specialty)")
            conn.commit()
    
    def record(self, specialty: str, task: str, response: str, success: bool):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO lessons (specialty, task, response, success, timestamp) VALUES (?,?,?,?,?)",
                (specialty, task[:500], response[:1000], 1 if success else 0, time.time())
            )
            conn.commit()
    
    def find_similar(self, specialty: str, task: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """بحث بسيط: keyword overlap."""
        task_words = set(task.lower().split())
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT task, response, success FROM lessons WHERE specialty = ? ORDER BY timestamp DESC LIMIT 50",
                (specialty,)
            )
            rows = cur.fetchall()
        
        scored = []
        for row in rows:
            prev_words = set(row[0].lower().split())
            overlap = len(task_words & prev_words)
            if overlap >= 2:
                scored.append((overlap, {"task": row[0], "response": row[1], "success": bool(row[2])}))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:top_k]]
    
    def stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM lessons")
            total = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM lessons WHERE success = 1")
            ok = cur.fetchone()[0]
        return {"total": total, "success": ok}
