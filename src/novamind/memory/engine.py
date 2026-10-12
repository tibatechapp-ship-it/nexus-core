"""MemoryEngine — Lightweight Long-Term Memory using SQLite."""
import sqlite3
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import Counter

log = logging.getLogger("MemoryEngine")


class MemoryEngine:
    """Simple, fast, persistent memory for agents."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MemoryEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # Ensure directory exists (NOVAMIND_HOME overrides the legacy path)
        db_dir = Path(os.environ.get("NOVAMIND_HOME", "/var/lib/hive"))
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "memory.db"
        
        self._init_db()
        log.info("MemoryEngine initialized at " + str(self.db_path))

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                task_summary TEXT NOT NULL,
                insight TEXT NOT NULL,
                full_content TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                tags TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent ON memories(agent_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_time ON memories(timestamp DESC)")
        conn.commit()
        conn.close()

    def _tokenize(self, text: str) -> List[str]:
        """Extract meaningful words for similarity search."""
        # Simple regex to find alphanumeric sequences
        words = re.findall(r"[a-zA-Z\u0600-\u06FF]+", text.lower())
        stop_words = {"the", "and", "for", "with", "this", "that", "في", "من", "إلى", "على"}
        return [w for w in words if len(w) > 2 and w not in stop_words]

    def _calculate_similarity(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        """Jaccard-like similarity score."""
        if not query_tokens or not doc_tokens:
            return 0.0
        
        q_set = set(query_tokens)
        d_set = set(doc_tokens)
        
        intersection = q_set.intersection(d_set)
        union = q_set.union(d_set)
        
        if not union:
            return 0.0
            
        return len(intersection) / len(union)

    def store_experience(
        self,
        agent_name: str,
        task_description: str,
        result_summary: str,
        success: bool,
        tags: Optional[List[str]] = None,
    ):
        """Store a new experience."""
        content_preview = "[" + agent_name + "] " + task_description[:50] + "... -> " + ("OK" if success else "FAIL")
        full_content = task_description + "\nResult: " + result_summary
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO memories (agent_name, task_summary, insight, full_content, success, tags, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    agent_name,
                    task_description[:200],
                    result_summary[:200],
                    full_content,
                    1 if success else 0,
                    ",".join(tags or []),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
            log.debug("Stored memory for " + agent_name)
        except Exception as e:
            log.error("Failed to store memory: " + str(e))
        finally:
            conn.close()

    def retrieve_similar_experiences(
        self,
        query: str,
        agent_name: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Retrieve most relevant past experiences."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        where_clause = "WHERE agent_name = ?" if agent_name else ""
        params = (agent_name,) if agent_name else ()
        
        cursor.execute(
            "SELECT id, agent_name, task_summary, insight, full_content, success, timestamp FROM memories " + where_clause + " ORDER BY id DESC LIMIT 50",
            params,
        )
        
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        query_tokens = self._tokenize(query)
        scored_results = []

        for row in rows:
            doc_id, ag_name, task_sum, insight, full_cont, succ_flag, ts = row
            
            doc_text = task_sum + " " + insight + " " + full_cont
            doc_tokens = self._tokenize(doc_text)
            
            score = self._calculate_similarity(query_tokens, doc_tokens)
            
            if score > 0.1: 
                scored_results.append({
                    "id": doc_id,
                    "agent": ag_name,
                    "content": task_sum + " | " + insight,
                    "success": bool(succ_flag),
                    "similarity_score": round(score, 3),
                    "timestamp": ts,
                })

        scored_results.sort(key=lambda x: -x["similarity_score"])
        return scored_results[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        """Return memory statistics."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM memories")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT agent_name, COUNT(*) FROM memories GROUP BY agent_name")
        by_agent = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            "total_memories": total,
            "by_agent": by_agent,
            "db_path": str(self.db_path),
            "backend": "sqlite-simple-tfidf"
        }

_engine_instance = None

def get_memory_engine() -> MemoryEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = MemoryEngine()
    return _engine_instance
