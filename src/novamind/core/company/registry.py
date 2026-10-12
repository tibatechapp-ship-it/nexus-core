"""Soldier Registry - يحفظ الجنود في SQLite للأبد."""
import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from novamind.core.company.soldier import Soldier
from novamind.core.company.ranks import Rank

logger = logging.getLogger("Registry")


class SoldierRegistry:
    """سجل دائم: الجنود لا يضيعون عند إغلاق النظام."""
    
    def __init__(self, db_path: str = "data/company/soldiers.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS soldiers (
                    id TEXT PRIMARY KEY,
                    specialty TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    rank_name TEXT NOT NULL,
                    signature TEXT,
                    system_prompt TEXT,
                    mission TEXT,
                    trust_score REAL DEFAULT 0.5,
                    tasks_completed INTEGER DEFAULT 0,
                    tasks_failed INTEGER DEFAULT 0,
                    total_time REAL DEFAULT 0.0,
                    hallucination_events INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL,
                    status TEXT DEFAULT 'active'
                );
                CREATE INDEX IF NOT EXISTS idx_specialty ON soldiers(specialty);
                CREATE INDEX IF NOT EXISTS idx_status ON soldiers(status);
                CREATE INDEX IF NOT EXISTS idx_rank ON soldiers(rank);

                CREATE TABLE IF NOT EXISTS soldier_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    soldier_id TEXT,
                    event_type TEXT,
                    data TEXT,
                    timestamp REAL,
                    FOREIGN KEY(soldier_id) REFERENCES soldiers(id)
                );
                CREATE INDEX IF NOT EXISTS idx_soldier_events ON soldier_events(soldier_id);
            """)
    
    def save(self, soldier: Soldier) -> bool:
        """يحفظ أو يحدّث جندياً."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO soldiers
                    (id, specialty, rank, rank_name, signature, system_prompt, mission,
                     trust_score, tasks_completed, tasks_failed, total_time,
                     hallucination_events, created_at, updated_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    soldier.id,
                    soldier.specialty,
                    soldier.rank.value,
                    soldier.rank.name,
                    soldier.signature,
                    soldier.system_prompt[:500],
                    soldier.mission[:200],
                    soldier.stats.trust_score,
                    soldier.stats.tasks_completed,
                    soldier.stats.tasks_failed,
                    soldier.stats.total_time,
                    soldier.stats.hallucination_events,
                    soldier.created_at.timestamp() if hasattr(soldier.created_at, 'timestamp') else time.time(),
                    time.time(),
                    "active",
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Save failed: {e}")
            return False
    
    def save_batch(self, soldiers: List[Soldier]) -> int:
        """يحفظ مجموعة جنود."""
        saved = 0
        for s in soldiers:
            if self.save(s):
                saved += 1
        return saved
    
    def load(self, soldier_id: str) -> Optional[Soldier]:
        """يحمّل جندياً من DB."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, specialty, rank_name, signature, system_prompt, mission, "
                "trust_score, tasks_completed, tasks_failed, total_time, hallucination_events "
                "FROM soldiers WHERE id = ?", (soldier_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_soldier(row)
    
    def load_all(self, status: str = "active") -> List[Soldier]:
        """يحمّل كل الجنود النشطين."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, specialty, rank_name, signature, system_prompt, mission, "
                "trust_score, tasks_completed, tasks_failed, total_time, hallucination_events "
                "FROM soldiers WHERE status = ?", (status,)
            )
            return [self._row_to_soldier(row) for row in cur.fetchall()]
    
    def _row_to_soldier(self, row) -> Soldier:
        """يحوّل صف DB إلى كائن Soldier."""
        sid, specialty, rank_name, signature, system_prompt, mission, \
        trust, tasks_ok, tasks_fail, total_time, hallucinations = row
        
        s = Soldier(
            specialty=specialty,
            rank=Rank[rank_name] if rank_name in Rank.__members__ else Rank.RECRUIT,
            system_prompt=system_prompt or "",
            mission=mission or "",
        )
        s.id = sid  # احتفظ بالمعرّف الأصلي
        s.signature = signature or s.signature
        s.stats.trust_score = trust
        s.stats.tasks_completed = tasks_ok
        s.stats.tasks_failed = tasks_fail
        s.stats.total_time = total_time
        s.stats.hallucination_events = hallucinations
        return s
    
    def record_event(self, soldier_id: str, event_type: str, data: Dict = None):
        """يسجّل حدثاً لجندي."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO soldier_events (soldier_id, event_type, data, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (soldier_id, event_type, json.dumps(data or {}), time.time())
            )
            conn.commit()
    
    def mark_status(self, soldier_id: str, status: str):
        """يحدّث حالة جندي (active/exiled/retired)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE soldiers SET status = ?, updated_at = ? WHERE id = ?",
                (status, time.time(), soldier_id)
            )
            conn.commit()
    
    def get_stats(self) -> Dict[str, Any]:
        """إحصائيات السجل."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM soldiers")
            total = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM soldiers WHERE status = 'active'")
            active = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM soldiers WHERE status = 'exiled'")
            exiled = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM soldier_events")
            events = cur.fetchone()[0]
        return {
            "total": total,
            "active": active,
            "exiled": exiled,
            "events": events,
        }
