"""Self-Learning Memory - يحفظ الدروس من كل مهمة."""
import json
import sqlite3
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("Memory")

class CompanyMemory:
    """ذاكرة الشركة: دروس + حلول + أنماط نجاح."""
    
    def __init__(self, db_path: str = "data/company/memory.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specialty TEXT,
                    task_pattern TEXT,
                    lesson TEXT,
                    success INTEGER,
                    agent_id TEXT,
                    timestamp REAL
                );
                CREATE INDEX IF NOT EXISTS idx_specialty ON lessons(specialty);
                CREATE INDEX IF NOT EXISTS idx_pattern ON lessons(task_pattern);
                
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specialty TEXT,
                    pattern_hash TEXT UNIQUE,
                    pattern_text TEXT,
                    best_response TEXT,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    timestamp REAL
                );
            """)
    
    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    def record_lesson(
        self,
        specialty: str,
        task: str,
        response: str,
        success: bool,
        agent_id: str = "unknown",
        lesson: str = "",
    ):
        """يحفظ درساً من مهمة."""
        pattern = self._hash(task[:200])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO lessons (specialty, task_pattern, lesson, success, agent_id, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (specialty, pattern, lesson or response[:500], 1 if success else 0,
                 agent_id, datetime.now().timestamp())
            )
            
            # تحديث patterns
            cur = conn.execute(
                "SELECT id, success_count, failure_count FROM patterns "
                "WHERE specialty = ? AND pattern_hash = ?",
                (specialty, pattern)
            )
            row = cur.fetchone()
            if row:
                if success:
                    conn.execute(
                        "UPDATE patterns SET success_count = success_count + 1, "
                        "best_response = ? WHERE id = ?",
                        (response[:1000], row[0])
                    )
                else:
                    conn.execute(
                        "UPDATE patterns SET failure_count = failure_count + 1 WHERE id = ?",
                        (row[0],)
                    )
            else:
                conn.execute(
                    "INSERT INTO patterns (specialty, pattern_hash, pattern_text, "
                    "best_response, success_count, failure_count, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (specialty, pattern, task[:500], response[:1000] if success else "",
                     1 if success else 0, 0 if success else 1, datetime.now().timestamp())
                )
            conn.commit()
    
    def get_best_response(self, specialty: str, task: str) -> Optional[str]:
        """يجد أفضل رد سابق لمهمة مشابهة."""
        pattern = self._hash(task[:200])
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT best_response, success_count, failure_count FROM patterns "
                "WHERE specialty = ? AND pattern_hash = ? AND success_count > failure_count",
                (specialty, pattern)
            )
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
        return None
    
    def get_recent_lessons(self, specialty: str = None, limit: int = 5) -> List[Dict]:
        """آخر الدروس المستفادة."""
        with sqlite3.connect(self.db_path) as conn:
            if specialty:
                cur = conn.execute(
                    "SELECT specialty, lesson, success, timestamp FROM lessons "
                    "WHERE specialty = ? ORDER BY timestamp DESC LIMIT ?",
                    (specialty, limit)
                )
            else:
                cur = conn.execute(
                    "SELECT specialty, lesson, success, timestamp FROM lessons "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                )
            return [
                {"specialty": r[0], "lesson": r[1], "success": bool(r[2]), "time": r[3]}
                for r in cur.fetchall()
            ]
    
    def stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM lessons")
            lessons_count = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM patterns WHERE success_count > failure_count")
            success_patterns = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM patterns WHERE failure_count >= success_count")
            failure_patterns = cur.fetchone()[0]
        return {
            "lessons": lessons_count,
            "success_patterns": success_patterns,
            "failure_patterns": failure_patterns,
        }
