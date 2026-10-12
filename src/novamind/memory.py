import sqlite3
import json
import time
import math
import logging
import httpx
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("MemoryManager")

class MemoryManager:
    """نظام الذاكرة الممتدة ثنائي الطبقات مع التوافقية التلقائية"""

    def __init__(
        self, 
        db_path: str = "novamind_memory.db", 
        ollama_url: str = "http://localhost:11434",
        embedding_model: str = "nomic-embed-text"
    ):
        self.db_path = db_path
        self.ollama_url = ollama_url
        self.embedding_model = embedding_model
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    embedding TEXT,
                    metadata TEXT,
                    timestamp REAL
                )
            """)
            conn.commit()

    def _fallback_embedding(self, text: str, dim: int = 768) -> List[float]:
        vec = [0.0] * dim
        for i, char in enumerate(text[:300]):
            vec[ord(char) % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def _get_embedding(self, text: str) -> List[float]:
        endpoint = f"{self.ollama_url}/api/embeddings"
        payload = {"model": self.embedding_model, "prompt": text}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.post(endpoint, json=payload)
                if res.status_code == 200:
                    emb = res.json().get("embedding", [])
                    if emb:
                        return emb
        except Exception:
            pass
        return self._fallback_embedding(text)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1)) or 1.0
        norm2 = math.sqrt(sum(b * b for b in vec2)) or 1.0
        return dot / (norm1 * norm2)

    async def add_memory(self, session_id: str, role: str, content: str, metadata: Dict[str, Any] = None):
        metadata = metadata or {}
        embedding = await self._get_embedding(content)
        timestamp = time.time()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO memories (session_id, role, content, embedding, metadata, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, json.dumps(embedding), json.dumps(metadata), timestamp)
            )
            conn.commit()

    def get_recent_history(self, session_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content FROM memories WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit)
            )
            rows = cursor.fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    async def recall_semantic_memories(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        query_vec = await self._get_embedding(query)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, session_id, role, content, embedding, metadata FROM memories")
            rows = cursor.fetchall()

        results = []
        for row in rows:
            mem_id, session_id, role, content, emb_json, meta_json = row
            emb = json.loads(emb_json)
            score = self._cosine_similarity(query_vec, emb)
            results.append({
                "id": mem_id,
                "role": role,
                "content": content,
                "score": score,
                "metadata": json.loads(meta_json or "{}")
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


# ═══ Module-level singleton ═══
memory = MemoryManager()


# Module-level singleton
memory = MemoryManager()
