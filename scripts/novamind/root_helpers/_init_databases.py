"""تهيئة قواعد البيانات للاختبارات."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / "hive" / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════
# 1. costs.db
# ═══════════════════════════════════════════════════════
costs_db = DB_DIR / "costs.db"
conn = sqlite3.connect(str(costs_db))
conn.execute("""
    CREATE TABLE IF NOT EXISTS costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        agent_id TEXT,
        provider TEXT,
        model TEXT,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0.0,
        duration REAL DEFAULT 0.0,
        success INTEGER DEFAULT 1,
        at TEXT
    )
""")
conn.commit()
conn.close()
print(f"OK costs.db: {costs_db}")

# ═══════════════════════════════════════════════════════
# 2. evaluations.db
# ═══════════════════════════════════════════════════════
evals_db = DB_DIR / "evaluations.db"
conn = sqlite3.connect(str(evals_db))
conn.execute("""
    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        agent_id TEXT,
        score REAL DEFAULT 0.0,
        success INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        duration REAL DEFAULT 0.0,
        at TEXT
    )
""")
conn.commit()
conn.close()
print(f"OK evaluations.db: {evals_db}")

print("\nDATABASES INITIALIZED")
