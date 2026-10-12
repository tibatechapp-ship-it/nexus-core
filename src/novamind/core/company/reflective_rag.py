"""Reflective RAG - Vector RAG + Self-Reflection في نموذج واحد."""
import asyncio
import hashlib
import json
import logging
import math
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ReflectiveRAG")


# ═══════════════════════════════════════════════════════
#  Simple Vector Store (بدون Qdrant — محلي بالكامل)
# ═══════════════════════════════════════════════════════
class LocalVectorStore:
    """متجر vectors محلي — يعمل بدون خدمات خارجية."""
    
    def __init__(self, db_path: str = "data/company/vector_memory.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specialty TEXT,
                    task TEXT,
                    task_hash TEXT,
                    response TEXT,
                    embedding TEXT,
                    success INTEGER,
                    score REAL,
                    timestamp REAL
                );
                CREATE INDEX IF NOT EXISTS idx_spec ON vectors(specialty);
                CREATE INDEX IF NOT EXISTS idx_hash ON vectors(task_hash);
            """)
    
    def _embed(self, text: str, dim: int = 256) -> List[float]:
        """Embedding محلي بسيط (hash-based TF)."""
        vec = [0.0] * dim
        words = re.findall(r'\w+', text.lower())
        for w in words:
            h = int(hashlib.md5(w.encode()).hexdigest()[:8], 16)
            vec[h % dim] += 1.0
        # تطبيع
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
    
    def _cosine(self, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (na * nb)
    
    def store(self, specialty: str, task: str, response: str, success: bool, score: float = 1.0):
        emb = self._embed(task)
        task_hash = hashlib.md5(task[:200].encode()).hexdigest()[:16]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO vectors (specialty, task, task_hash, response, embedding, success, score, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (specialty, task[:500], task_hash, response[:2000], json.dumps(emb), 1 if success else 0, score, time.time())
            )
            conn.commit()
    
    def search(self, specialty: str, task: str, top_k: int = 5) -> List[Dict]:
        query_vec = self._embed(task)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT task, response, embedding, success, score FROM vectors "
                "WHERE specialty = ? ORDER BY timestamp DESC LIMIT 200",
                (specialty,)
            )
            rows = cur.fetchall()
        
        scored = []
        for row in rows:
            try:
                emb = json.loads(row[2])
                sim = self._cosine(query_vec, emb)
                if sim > 0.15:  # threshold
                    scored.append({
                        "task": row[0],
                        "response": row[1],
                        "success": bool(row[3]),
                        "score": row[4],
                        "similarity": round(sim, 3),
                    })
            except Exception:
                pass
        
        scored.sort(key=lambda x: (x["similarity"], x["score"]), reverse=True)
        return scored[:top_k]
    
    def stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM vectors")
            total = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM vectors WHERE success = 1")
            ok = cur.fetchone()[0]
        return {"total": total, "success": ok, "failed": total - ok}


# ═══════════════════════════════════════════════════════
#  Reflective RAG — النموذج الموحّد
# ═══════════════════════════════════════════════════════
class ReflectiveRAG:
    """نموذج واحد: Vector RAG + Self-Reflection."""
    
    def __init__(self, llm_router, vector_store: Optional[LocalVectorStore] = None):
        self.llm = llm_router
        self.store = vector_store or LocalVectorStore()
        self.stats = {
            "generations": 0,
            "reflections": 0,
            "revisions": 0,
            "verifications": 0,
            "stored": 0,
            "rag_hits": 0,
        }
    
    # ═══════════════════════════════════════════════════
    #  المرحلة 1: RAG Retrieval
    # ═══════════════════════════════════════════════════
    def _retrieve_context(self, specialty: str, task: str) -> Tuple[str, int]:
        """يسترجع دروس شبيهة ويبني نص السياق."""
        similar = self.store.search(specialty, task, top_k=5)
        if not similar:
            return "", 0
        
        lines = ["## PAST LESSONS (learn from these):\n"]
        for i, s in enumerate(similar, 1):
            status = "✅" if s["success"] else "❌"
            lines.append(f"### Lesson {i} {status} (sim={s['similarity']})")
            lines.append(f"Task: {s['task'][:200]}")
            lines.append(f"Response: {s['response'][:400]}\n")
        
        self.stats["rag_hits"] += 1
        return "\n".join(lines), len(similar)
    
    # ═══════════════════════════════════════════════════
    #  المرحلة 2: Generate
    # ═══════════════════════════════════════════════════
    async def _generate(self, task: str, system_prompt: str, context: str) -> str:
        prompt = f"{context}\n\n## YOUR TASK\n{task}\n\nOutput ONLY the solution."
        response = await asyncio.wait_for(
            self.llm.generate(prompt, system_prompt=system_prompt),
            timeout=180.0,
        )
        self.stats["generations"] += 1
        return response
    
    # ═══════════════════════════════════════════════════
    #  المرحلة 3: Self-Critique
    # ═══════════════════════════════════════════════════
    async def _critique(self, task: str, response: str) -> Dict[str, Any]:
        """النموذج ينقد نفسه."""
        prompt = f"""You are a CRITICAL reviewer. Analyze this response honestly.

TASK:
{task[:500]}

RESPONSE:
{response[:1500]}

Answer with JSON only:
{{
  "quality": "excellent|good|poor",
  "issues": ["issue1", "issue2"],
  "should_revise": true|false,
  "reason": "short reason"
}}"""
        
        try:
            result = await asyncio.wait_for(
                self.llm.generate(prompt, system_prompt="You are a critical code reviewer."),
                timeout=60.0,
            )
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                self.stats["reflections"] += 1
                return data
        except Exception as e:
            logger.debug(f"Critique failed: {e}")
        
        return {"should_revise": False, "quality": "unknown"}
    
    # ═══════════════════════════════════════════════════
    #  المرحلة 4: Revise
    # ═══════════════════════════════════════════════════
    async def _revise(self, task: str, response: str, critique: Dict) -> str:
        issues = critique.get("issues", [])
        if not issues:
            return response
        
        prompt = f"""Improve this response based on critique.

TASK:
{task[:500]}

ORIGINAL:
{response[:1500]}

ISSUES TO FIX:
{chr(10).join(f"- {i}" for i in issues)}

Output ONLY the improved solution."""
        
        try:
            revised = await asyncio.wait_for(
                self.llm.generate(prompt, system_prompt="You are an expert improver."),
                timeout=180.0,
            )
            self.stats["revisions"] += 1
            return revised
        except Exception:
            return response
    
    # ═══════════════════════════════════════════════════
    #  المرحلة 5: Verify
    # ═══════════════════════════════════════════════════
    async def _verify(self, task: str, response: str) -> Dict[str, Any]:
        prompt = f"""Final verification. Is this response correct and complete?

TASK:
{task[:500]}

RESPONSE:
{response[:1500]}

Answer JSON:
{{
  "approved": true|false,
  "confidence": 0.0-1.0,
  "final_reason": "short"
}}"""
        
        try:
            result = await asyncio.wait_for(
                self.llm.generate(prompt, system_prompt="You are a final verifier."),
                timeout=60.0,
            )
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                self.stats["verifications"] += 1
                return data
        except Exception:
            pass
        
        return {"approved": True, "confidence": 0.5}
    
    # ═══════════════════════════════════════════════════
    #  الواجهة الرئيسية: 6 مراحل
    # ═══════════════════════════════════════════════════
    async def execute(
        self,
        task: str,
        system_prompt: str,
        specialty: str = "generic",
        max_reflections: int = 2,
    ) -> Dict[str, Any]:
        """ينفذ مهمة بـ 6 مراحل."""
        t0 = time.time()
        trace = []
        
        # ═══ 1. RAG ═══
        context, hits = self._retrieve_context(specialty, task)
        trace.append({"step": "rag", "hits": hits})
        logger.info(f"RAG: {hits} lessons found")
        
        # ═══ 2. Generate ═══
        response = await self._generate(task, system_prompt, context)
        trace.append({"step": "generate", "length": len(response)})
        logger.info(f"Generated: {len(response)} chars")
        
        # ═══ 3-4. Reflection Loop ═══
        final_response = response
        for i in range(max_reflections):
            critique = await self._critique(task, final_response)
            trace.append({"step": f"critique_{i}", "quality": critique.get("quality")})
            
            if not critique.get("should_revise"):
                logger.info(f"Critique {i}: approved, no revision needed")
                break
            
            logger.info(f"Critique {i}: revise → {critique.get('issues', [])[:2]}")
            revised = await self._revise(task, final_response, critique)
            final_response = revised
            trace.append({"step": f"revise_{i}", "length": len(revised)})
        
        # ═══ 5. Verify ═══
        verification = await self._verify(task, final_response)
        trace.append({"step": "verify", "approved": verification.get("approved")})
        logger.info(f"Verify: approved={verification.get('approved')}")
        
        # ═══ 6. Store ═══
        success = verification.get("approved", False)
        score = verification.get("confidence", 0.5)
        self.store.store(specialty, task, final_response, success, score)
        self.stats["stored"] += 1
        
        dt = time.time() - t0
        
        return {
            "status": "success" if success else "unverified",
            "response": final_response,
            "rag_hits": hits,
            "verification": verification,
            "trace": trace,
            "time": round(dt, 2),
        }
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "vector_store": self.store.stats(),
        }
