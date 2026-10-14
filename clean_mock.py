import os, json, glob, sqlite3, shutil
H = os.path.expanduser("~")
DATA = os.path.join(H, ".nexus", "data")

BAD = ("هل نضيف تشفير لتخزين rag في nexus-core؟",
       "هل نضيف تشفير لطبقة rag في nexus-core؟")

# 1) history الوهمي
HD = os.path.join(DATA, "council_history")
removed = 0
if os.path.isdir(HD):
    for f in glob.glob(os.path.join(HD, "*.json")):
        try:
            r = json.load(open(f, encoding="utf-8"))
            q = (r.get("query") or "").lower()
            if any(b in q for b in BAD):
                os.remove(f)
                removed += 1
        except Exception:
            pass
print("history: حُذف", removed, "سجل mock")

# 2) وثائق test_ من RAG
db = os.path.join(DATA, "rag.db")
if os.path.exists(db):
    con = sqlite3.connect(db)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    total = 0
    for t in tables:
        cols = [c[1] for c in cur.execute("PRAGMA table_info(%s)" % t).fetchall()]
        # ابحث عن عمود id أو text
        for col in cols:
            try:
                n = cur.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s LIKE 'test_%%'" % (t, col)
                ).fetchone()[0]
                if n > 0:
                    cur.execute(
                        "DELETE FROM %s WHERE %s LIKE 'test_%%'" % (t, col))
                    total += n
                    print("  %s.%s: حُذف %d" % (t, col, n))
            except Exception:
                pass
    con.commit()
    con.close()
    print("RAG: حُذف", total, "صف test_")

# 3) الكاش
for name in ("council_cache", "agent_cache"):
    p = os.path.join(DATA, name)
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
        print("cache: حُذف", name)
print("CLEAN_DONE")
