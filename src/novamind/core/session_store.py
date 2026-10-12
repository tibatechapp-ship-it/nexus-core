"""SQLite persistence for nexus-core chat sessions (v1.5).

A tiny, dependency-free store (stdlib ``sqlite3`` only) that owns the
``sessions.db`` database.  It replaces the browser ``localStorage`` as the
source of truth for conversations and messages, and reserves two tables for
the upcoming Living-Council feature.

Design notes
------------
* Pure stdlib — works on the phone with zero optional extras installed.
* A connection is opened per operation, so the store is safe to call from
  FastAPI's thread pool without shared-connection locking games.
* WAL journal mode for concurrent reads while a write is in flight.
* ``PRAGMA user_version`` tracks the schema revision for future migrations.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    agent       TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    ts              INTEGER NOT NULL,
    meta            TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, ts);

CREATE TABLE IF NOT EXISTS council_sessions (
    id          TEXT PRIMARY KEY,
    topic       TEXT NOT NULL DEFAULT '',
    rounds      INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    verdict     TEXT NOT NULL DEFAULT '',
    consensus   REAL NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS council_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    round       INTEGER NOT NULL DEFAULT 0,
    agent       TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    ts          INTEGER NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (session_id) REFERENCES council_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_councilmsg_sess ON council_messages(session_id, round, ts);

CREATE TABLE IF NOT EXISTS traces (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    response        TEXT NOT NULL DEFAULT '',
    agent           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'ok',
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    plan            TEXT NOT NULL DEFAULT '{}',
    gatekeeper      TEXT NOT NULL DEFAULT '{}',
    pre_check       TEXT NOT NULL DEFAULT '{}',
    ts              INTEGER NOT NULL,
    meta            TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_traces_conv ON traces(conversation_id, ts);
CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(ts DESC);

CREATE TABLE IF NOT EXISTS agent_genome (
    agent_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    persona         TEXT NOT NULL DEFAULT '',
    generation      INTEGER NOT NULL DEFAULT 1,
    parent_id       TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    runs            INTEGER NOT NULL DEFAULT 0,
    successes       INTEGER NOT NULL DEFAULT 0,
    failures        INTEGER NOT NULL DEFAULT 0,
    latency_sum_ms  INTEGER NOT NULL DEFAULT 0,
    consensus_sum   REAL NOT NULL DEFAULT 0,
    consensus_n     INTEGER NOT NULL DEFAULT 0,
    standing        REAL NOT NULL DEFAULT 0.5,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    meta            TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS genome_events (
    id       TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind     TEXT NOT NULL DEFAULT '',
    detail   TEXT NOT NULL DEFAULT '{}',
    ts       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_genome_events ON genome_events(agent_id, ts);
"""


def _now_ms() -> int:
    """Current time in milliseconds (the unit the UI already uses)."""
    return int(time.time() * 1000)


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:16]


def default_db_path() -> Path:
    """Resolve the database path.

    Priority: ``$NEXUS_DB`` → ``<repo_root>/data/sessions.db``.  Falls back to
    ``$TMPDIR`` if the ``data/`` directory cannot be created (e.g. read-only).
    """
    env = os.environ.get("NEXUS_DB")
    if env:
        return Path(env).expanduser()
    root = Path(__file__).resolve().parents[3]
    data_dir = root / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_test"
        probe.touch()
        probe.unlink()
        return data_dir / "sessions.db"
    except OSError:
        import tempfile

        fallback = Path(tempfile.gettempdir()) / "nexus-core"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "sessions.db"


class SessionStore:
    """Thin, typed wrapper over the sessions SQLite database."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    # ── low level ────────────────────────────────────────────────────────
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _sql(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return list(conn.execute(query, params).fetchall())

    @staticmethod
    def _row_to_conv(row: sqlite3.Row, message_count: Optional[int] = None,
                     preview: str = "") -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": row["id"],
            "title": row["title"],
            "agent": row["agent"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "date": row["updated_at"],  # UI expects `date`
            "meta": json.loads(row["meta"] or "{}"),
        }
        if message_count is not None:
            out["message_count"] = message_count
        if preview:
            out["preview"] = preview
        return out

    @staticmethod
    def _row_to_msg(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "ts": row["ts"],
            "meta": json.loads(row["meta"] or "{}"),
        }

    # ── conversations ────────────────────────────────────────────────────
    def create_conversation(self, conv_id: Optional[str] = None,
                            title: str = "", agent: str = "",
                            meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        conv_id = conv_id or _new_id("c")
        now = _now_ms()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id,title,agent,created_at,updated_at,meta)"
                " VALUES (?,?,?,?,?,?)",
                (conv_id, title, agent, now, now, json.dumps(meta or {}, ensure_ascii=False)),
            )
        return {"id": conv_id, "title": title, "agent": agent,
                "created_at": now, "updated_at": now, "date": now, "meta": meta or {},
                "message_count": 0, "messages": []}

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        if not rows:
            return None
        conv = self._row_to_conv(rows[0])
        msgs = self._sql(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY ts ASC", (conv_id,)
        )
        conv["messages"] = [self._row_to_msg(m) for m in msgs]
        conv["message_count"] = len(conv["messages"])
        return conv

    def list_conversations(self, limit: int = 500) -> List[Dict[str, Any]]:
        rows = self._sql(
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id)"
            " AS cnt,"
            " (SELECT content FROM messages m2 WHERE m2.conversation_id=c.id"
            "  ORDER BY ts DESC LIMIT 1) AS preview"
            " FROM conversations c ORDER BY updated_at DESC LIMIT ?",
            (int(limit),),
        )
        return [
            self._row_to_conv(r, message_count=r["cnt"],
                              preview=(r["preview"] or "")[:140])
            for r in rows
        ]

    def update_conversation(self, conv_id: str, title: Optional[str] = None,
                            agent: Optional[str] = None,
                            meta: Optional[Dict[str, Any]] = None) -> bool:
        sets: List[str] = []
        params: List[Any] = []
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if agent is not None:
            sets.append("agent = ?")
            params.append(agent)
        if meta is not None:
            sets.append("meta = ?")
            params.append(json.dumps(meta, ensure_ascii=False))
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(_now_ms())
        params.append(conv_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?", tuple(params)
            )
            return cur.rowcount > 0

    def delete_conversation(self, conv_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return cur.rowcount > 0

    def clear_conversations(self) -> int:
        with self._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            conn.execute("DELETE FROM conversations")
            return int(n)

    # ── messages ─────────────────────────────────────────────────────────
    def add_message(self, conv_id: str, role: str, content: str,
                    meta: Optional[Dict[str, Any]] = None,
                    ts: Optional[int] = None) -> Dict[str, Any]:
        msg_id = _new_id("m")
        ts = ts if ts is not None else _now_ms()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (id,conversation_id,role,content,ts,meta)"
                " VALUES (?,?,?,?,?,?)",
                (msg_id, conv_id, role, content, ts,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, conv_id)
            )
        return {"id": msg_id, "conversation_id": conv_id, "role": role,
                "content": content, "ts": ts, "meta": meta or {}}

    def delete_message(self, msg_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
            return cur.rowcount > 0

    def replace_messages(self, conv_id: str, messages: List[Dict[str, Any]]) -> int:
        """Replace a conversation's whole message list (client-authoritative sync).

        Simplest correct model for the UI: the browser owns the in-memory thread
        and pushes the full list after any edit / regenerate / delete.
        """
        now = _now_ms()
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            for m in messages:
                conn.execute(
                    "INSERT INTO messages (id,conversation_id,role,content,ts,meta)"
                    " VALUES (?,?,?,?,?,?)",
                    (_new_id("m"), conv_id, str(m.get("role") or "user"),
                     str(m.get("content") or ""), int(m.get("ts") or now),
                     json.dumps(m.get("meta") or {}, ensure_ascii=False)),
                )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id)
            )
        return len(messages)

    def truncate_from(self, conv_id: str, from_ts: int) -> int:
        """Delete every message with ``ts >= from_ts`` in a conversation.

        Used by the UI's edit/regenerate flow to drop the tail before a retry.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND ts >= ?",
                (conv_id, from_ts),
            )
            return cur.rowcount

    # ── search / export ──────────────────────────────────────────────────
    def search_conversations(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        q = f"%{query.strip()}%"
        rows = self._sql(
            "SELECT DISTINCT c.* FROM conversations c"
            " LEFT JOIN messages m ON m.conversation_id = c.id"
            " WHERE c.title LIKE ? OR m.content LIKE ?"
            " ORDER BY c.updated_at DESC LIMIT ?",
            (q, q, int(limit)),
        )
        return [self._row_to_conv(r) for r in rows]

    def export_conversation(self, conv_id: str, fmt: str = "json") -> Optional[str]:
        conv = self.get_conversation(conv_id)
        if conv is None:
            return None
        if fmt in ("md", "markdown"):
            return self._to_markdown(conv)
        return json.dumps(conv, ensure_ascii=False, indent=2)

    def export_all_conversations(self, fmt: str = "json", limit: int = 10000) -> str:
        """Export every conversation (with messages) for backup / migration."""
        convs = [self.get_conversation(c["id"]) for c in self.list_conversations(limit=limit)]
        convs = [c for c in convs if c]
        if fmt in ("md", "markdown"):
            return "\n\n---\n\n".join(self._to_markdown(c) for c in convs)
        return json.dumps({"conversations": convs}, ensure_ascii=False, indent=2)

    @staticmethod
    def _to_markdown(conv: Dict[str, Any]) -> str:
        lines = [f"# {conv.get('title') or 'محادثة'}", ""]
        lines.append(f"- id: `{conv['id']}`")
        lines.append(f"- agent: `{conv.get('agent') or 'auto'}`")
        lines.append(f"- messages: {len(conv['messages'])}")
        lines.append("")
        for m in conv["messages"]:
            who = "👤" if m["role"] == "user" else "🤖"
            lines.append(f"## {who} {m['role']}")
            lines.append("")
            lines.append(m["content"])
            lines.append("")
        return "\n".join(lines)

    # ── migration ────────────────────────────────────────────────────────
    def import_conversations(self, conversations: List[Dict[str, Any]]) -> int:
        """Import the old localStorage payload. Idempotent by conversation id."""
        imported = 0
        for conv in conversations:
            cid = str(conv.get("id") or _new_id("c"))
            if self._sql("SELECT id FROM conversations WHERE id = ?", (cid,)):
                continue
            now = _now_ms()
            created = int(conv.get("date") or now)
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO conversations (id,title,agent,created_at,updated_at,meta)"
                    " VALUES (?,?,?,?,?,?)",
                    (cid, str(conv.get("title") or ""), str(conv.get("agent") or ""),
                     created, created,
                     json.dumps(conv.get("meta") or {}, ensure_ascii=False)),
                )
                for m in conv.get("messages") or []:
                    conn.execute(
                        "INSERT INTO messages (id,conversation_id,role,content,ts,meta)"
                        " VALUES (?,?,?,?,?,?)",
                        (_new_id("m"), cid, str(m.get("role") or "user"),
                         str(m.get("content") or ""), int(m.get("ts") or now), "{}"),
                    )
            imported += 1
        return imported

    # ── council (reserved for v2.0) ──────────────────────────────────────
    def create_council_session(self, topic: str, rounds: int = 0,
                               meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sid = _new_id("cs")
        now = _now_ms()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO council_sessions (id,topic,rounds,status,verdict,consensus,"
                "created_at,updated_at,meta) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, topic, rounds, "pending", "", 0.0, now, now,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
        return {"id": sid, "topic": topic, "rounds": rounds, "status": "pending",
                "verdict": "", "consensus": 0.0, "created_at": now, "updated_at": now}

    def add_council_message(self, session_id: str, round_no: int, agent: str,
                            content: str, role: str = "opinion",
                            meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        mid = _new_id("cm")
        ts = _now_ms()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO council_messages (id,session_id,round,agent,role,content,ts,meta)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (mid, session_id, round_no, agent, role, content, ts,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
        return {"id": mid, "session_id": session_id, "round": round_no,
                "agent": agent, "role": role, "content": content, "ts": ts}

    def update_council_session(self, session_id: str, **fields: Any) -> bool:
        allowed = {"topic", "rounds", "status", "verdict", "consensus"}
        sets = [f"{k} = ?" for k in fields if k in allowed]
        if not sets:
            return False
        params = [fields[k] for k in fields if k in allowed]
        sets.append("updated_at = ?")
        params.append(_now_ms())
        params.append(session_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE council_sessions SET {', '.join(sets)} WHERE id = ?", tuple(params)
            )
            return cur.rowcount > 0

    def get_council_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql("SELECT * FROM council_sessions WHERE id = ?", (session_id,))
        if not rows:
            return None
        r = rows[0]
        sess = {k: r[k] for k in r.keys()}
        sess["meta"] = json.loads(sess.get("meta") or "{}")
        msgs = self._sql(
            "SELECT * FROM council_messages WHERE session_id = ? ORDER BY round, ts",
            (session_id,),
        )
        sess["messages"] = [
            {k: m[k] for k in m.keys()} for m in msgs
        ]
        for m in sess["messages"]:
            m["meta"] = json.loads(m.get("meta") or "{}")
        return sess

    def list_council_sessions(self, limit: int = 50,
                              newest_first: bool = True) -> List[Dict[str, Any]]:
        order = "DESC" if newest_first else "ASC"
        rows = self._sql(
            f"SELECT * FROM council_sessions ORDER BY created_at {order} LIMIT ?",
            (int(limit),),
        )
        out: List[Dict[str, Any]] = []
        for r in rows:
            s = {k: r[k] for k in r.keys()}
            s["meta"] = json.loads(s.get("meta") or "{}")
            out.append(s)
        return out

    def list_council_messages(self, session_id: str) -> List[Dict[str, Any]]:
        rows = self._sql(
            "SELECT * FROM council_messages WHERE session_id = ? ORDER BY round, ts",
            (session_id,),
        )
        out: List[Dict[str, Any]] = []
        for m in rows:
            d = {k: m[k] for k in m.keys()}
            d["meta"] = json.loads(d.get("meta") or "{}")
            out.append(d)
        return out

    def delete_council_session(self, session_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM council_messages WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM council_sessions WHERE id = ?", (session_id,))
            return cur.rowcount > 0

    # ── time machine: traces (v1.5) ──────────────────────────────────────
    @staticmethod
    def _json_field(value: Any) -> str:
        """Coerce a value (dict / str / None) into a JSON text column."""
        if value is None:
            return "{}"
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except (ValueError, TypeError):
                return json.dumps({"text": value}, ensure_ascii=False)
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "message": row["message"],
            "response": row["response"],
            "agent": row["agent"],
            "status": row["status"],
            "latency_ms": row["latency_ms"],
            "plan": json.loads(row["plan"] or "{}"),
            "gatekeeper": json.loads(row["gatekeeper"] or "{}"),
            "pre_check": json.loads(row["pre_check"] or "{}"),
            "ts": row["ts"],
            "meta": json.loads(row["meta"] or "{}"),
        }

    def add_trace(self, conversation_id: str, message: str, response: str,
                  agent: str = "", status: str = "ok", latency_ms: int = 0,
                  plan: Any = None, gatekeeper: Any = None, pre_check: Any = None,
                  meta: Optional[Dict[str, Any]] = None,
                  ts: Optional[int] = None) -> Dict[str, Any]:
        """Record one chat request → response pair (the Time-Machine log)."""
        tid = _new_id("t")
        ts = ts if ts is not None else _now_ms()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO traces (id,conversation_id,message,response,agent,status,"
                "latency_ms,plan,gatekeeper,pre_check,ts,meta)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, conversation_id or "", message or "", response or "", agent or "",
                 status or "ok", int(latency_ms or 0), self._json_field(plan),
                 self._json_field(gatekeeper), self._json_field(pre_check), ts,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
        return {"id": tid, "conversation_id": conversation_id or "", "message": message or "",
                "response": response or "", "agent": agent or "", "status": status or "ok",
                "latency_ms": int(latency_ms or 0), "plan": plan or {},
                "gatekeeper": gatekeeper or {}, "pre_check": pre_check or {},
                "ts": ts, "meta": meta or {}}

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql("SELECT * FROM traces WHERE id = ?", (trace_id,))
        return self._row_to_trace(rows[0]) if rows else None

    def list_traces(self, conversation_id: Optional[str] = None,
                    limit: int = 200, newest_first: bool = True) -> List[Dict[str, Any]]:
        order = "DESC" if newest_first else "ASC"
        if conversation_id:
            rows = self._sql(
                f"SELECT * FROM traces WHERE conversation_id = ? ORDER BY ts {order} LIMIT ?",
                (conversation_id, int(limit)),
            )
        else:
            rows = self._sql(
                f"SELECT * FROM traces ORDER BY ts {order} LIMIT ?", (int(limit),)
            )
        return [self._row_to_trace(r) for r in rows]

    def search_traces(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        q = f"%{query.strip()}%"
        rows = self._sql(
            "SELECT * FROM traces WHERE message LIKE ? OR response LIKE ? OR agent LIKE ?"
            " ORDER BY ts DESC LIMIT ?",
            (q, q, q, int(limit)),
        )
        return [self._row_to_trace(r) for r in rows]

    def delete_trace(self, trace_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM traces WHERE id = ?", (trace_id,))
            return cur.rowcount > 0

    def clear_traces(self, conversation_id: Optional[str] = None) -> int:
        with self._connect() as conn:
            if conversation_id:
                cur = conn.execute(
                    "DELETE FROM traces WHERE conversation_id = ?", (conversation_id,)
                )
            else:
                cur = conn.execute("DELETE FROM traces")
            return cur.rowcount

    def export_trace(self, trace_id: str, fmt: str = "json") -> Optional[str]:
        tr = self.get_trace(trace_id)
        if tr is None:
            return None
        if fmt in ("md", "markdown"):
            return self._trace_to_markdown(tr)
        return json.dumps(tr, ensure_ascii=False, indent=2)

    @staticmethod
    def _trace_to_markdown(tr: Dict[str, Any]) -> str:
        import datetime as _dt

        when = _dt.datetime.fromtimestamp(tr["ts"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "# 🔭 Time Machine — trace",
            "",
            f"- id: `{tr['id']}`",
            f"- when: {when}",
            f"- conversation: `{tr['conversation_id'] or '—'}`",
            f"- agent: `{tr['agent'] or 'auto'}`",
            f"- status: {tr['status']}",
            f"- latency: {tr['latency_ms']} ms",
            "",
            "## ❓ Request",
            "",
            tr["message"],
            "",
            "## 💬 Response",
            "",
            tr["response"],
            "",
        ]
        if tr.get("plan"):
            lines += ["## 🧭 Plan", "", "```json",
                      json.dumps(tr["plan"], ensure_ascii=False, indent=2), "```", ""]
        return "\n".join(lines)

    # ── genome (v2.2 — Agent Genome) ─────────────────────────────────────
    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> Dict[str, Any]:
        d = {k: row[k] for k in row.keys()}
        d["meta"] = json.loads(d.get("meta") or "{}")
        return d

    def upsert_agent(self, agent_id: str, name: str = "", persona: str = "",
                     parent_id: str = "", generation: int = 1,
                     meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a genome row if absent; return the row either way."""
        now = _now_ms()
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT agent_id FROM agent_genome WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if exists is None:
                conn.execute(
                    "INSERT INTO agent_genome (agent_id,name,persona,generation,parent_id,"
                    "status,created_at,updated_at,meta) VALUES (?,?,?,?,?,?,?,?,?)",
                    (agent_id, name, persona, int(generation), parent_id, "active",
                     now, now, json.dumps(meta or {}, ensure_ascii=False)),
                )
                conn.execute(
                    "INSERT INTO genome_events (id,agent_id,kind,detail,ts)"
                    " VALUES (?,?,?,?,?)",
                    (_new_id("g"), agent_id, "born",
                     json.dumps({"name": name}, ensure_ascii=False), now),
                )
        row = self.get_agent(agent_id)
        assert row is not None
        return row

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        rows = self._sql("SELECT * FROM agent_genome WHERE agent_id = ?", (agent_id,))
        return self._row_to_agent(rows[0]) if rows else None

    def list_agents(self) -> List[Dict[str, Any]]:
        rows = self._sql(
            "SELECT * FROM agent_genome ORDER BY standing DESC, runs DESC, name ASC"
        )
        return [self._row_to_agent(r) for r in rows]

    def update_agent(self, agent_id: str, name: Optional[str] = None,
                     persona: Optional[str] = None, status: Optional[str] = None,
                     meta: Optional[Dict[str, Any]] = None) -> bool:
        sets: List[str] = []
        params: List[Any] = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if persona is not None:
            sets.append("persona = ?")
            params.append(persona)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if meta is not None:
            sets.append("meta = ?")
            params.append(json.dumps(meta, ensure_ascii=False))
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(_now_ms())
        params.append(agent_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE agent_genome SET {', '.join(sets)} WHERE agent_id = ?",
                tuple(params),
            )
            ok = cur.rowcount > 0
            if ok:
                conn.execute(
                    "INSERT INTO genome_events (id,agent_id,kind,detail,ts)"
                    " VALUES (?,?,?,?,?)",
                    (_new_id("g"), agent_id, "edit",
                     json.dumps({"fields": [s.split(" =")[0] for s in sets
                                            if not s.startswith("updated_at")]},
                                ensure_ascii=False), _now_ms()),
                )
            return ok

    def record_agent_outcome(self, agent_id: str, success: bool, latency_ms: int = 0,
                             consensus: Optional[float] = None,
                             standing: Optional[float] = None,
                             status: Optional[str] = None, kind: str = "outcome",
                             detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Append one outcome to an agent's stats. Standing/status come from the
        caller (the Genome manager owns the scoring math)."""
        now = _now_ms()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_genome WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO agent_genome (agent_id,name,created_at,updated_at)"
                    " VALUES (?,?,?,?)",
                    (agent_id, agent_id, now, now),
                )
                row = conn.execute(
                    "SELECT * FROM agent_genome WHERE agent_id = ?", (agent_id,)
                ).fetchone()
            assert row is not None
            runs = int(row["runs"]) + 1
            successes = int(row["successes"]) + (1 if success else 0)
            failures = int(row["failures"]) + (0 if success else 1)
            latency_sum = int(row["latency_sum_ms"]) + int(latency_ms or 0)
            consensus_sum = float(row["consensus_sum"]) + float(consensus or 0.0)
            consensus_n = int(row["consensus_n"]) + (1 if consensus is not None else 0)
            new_standing = float(standing) if standing is not None else float(row["standing"])
            new_status = status or str(row["status"]) or "active"
            conn.execute(
                "UPDATE agent_genome SET runs=?,successes=?,failures=?,latency_sum_ms=?,"
                "consensus_sum=?,consensus_n=?,standing=?,status=?,updated_at=?"
                " WHERE agent_id=?",
                (runs, successes, failures, latency_sum, consensus_sum, consensus_n,
                 new_standing, new_status, now, agent_id),
            )
            conn.execute(
                "INSERT INTO genome_events (id,agent_id,kind,detail,ts) VALUES (?,?,?,?,?)",
                (_new_id("g"), agent_id, kind,
                 json.dumps({
                     "success": bool(success),
                     "latency_ms": int(latency_ms or 0),
                     "consensus": consensus,
                     "standing": round(new_standing, 4),
                     **(detail or {}),
                 }, ensure_ascii=False), now),
            )
        out = self.get_agent(agent_id)
        assert out is not None
        return out

    def reset_agent(self, agent_id: str, note: str = "") -> Optional[Dict[str, Any]]:
        """Re-train: zero stats, neutral standing, bump generation."""
        now = _now_ms()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generation FROM agent_genome WHERE agent_id = ?", (agent_id,)
            ).fetchone()
            if row is None:
                return None
            gen = int(row["generation"]) + 1
            conn.execute(
                "UPDATE agent_genome SET runs=0,successes=0,failures=0,latency_sum_ms=0,"
                "consensus_sum=0,consensus_n=0,standing=0.5,status='active',"
                "generation=?,updated_at=? WHERE agent_id=?",
                (gen, now, agent_id),
            )
            conn.execute(
                "INSERT INTO genome_events (id,agent_id,kind,detail,ts) VALUES (?,?,?,?,?)",
                (_new_id("g"), agent_id, "reset",
                 json.dumps({"generation": gen, "note": note}, ensure_ascii=False), now),
            )
        return self.get_agent(agent_id)

    def agent_timeline(self, agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self._sql(
            "SELECT * FROM genome_events WHERE agent_id = ? ORDER BY ts DESC LIMIT ?",
            (agent_id, int(limit)),
        )
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            d["detail"] = json.loads(d.get("detail") or "{}")
            out.append(d)
        return out

    def genome_import(self, agents: List[Dict[str, Any]]) -> int:
        """Insert agents (and their events) that are not already present."""
        imported = 0
        now = _now_ms()
        for a in agents:
            agent_id = str(a.get("agent_id") or "")
            if not agent_id or self.get_agent(agent_id) is not None:
                continue
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO agent_genome (agent_id,name,persona,generation,parent_id,"
                    "status,runs,successes,failures,latency_sum_ms,consensus_sum,consensus_n,"
                    "standing,created_at,updated_at,meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (agent_id, str(a.get("name") or ""), str(a.get("persona") or ""),
                     int(a.get("generation") or 1), str(a.get("parent_id") or ""),
                     str(a.get("status") or "active"), int(a.get("runs") or 0),
                     int(a.get("successes") or 0), int(a.get("failures") or 0),
                     int(a.get("latency_sum_ms") or 0), float(a.get("consensus_sum") or 0),
                     int(a.get("consensus_n") or 0), float(a.get("standing") or 0.5),
                     int(a.get("created_at") or now), int(a.get("updated_at") or now),
                     json.dumps(a.get("meta") or {}, ensure_ascii=False)),
                )
            imported += 1
        return imported

    # ── stats ────────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        def count(table: str) -> int:
            rows = self._sql(f"SELECT COUNT(*) AS n FROM {table}")
            return int(rows[0]["n"]) if rows else 0

        return {
            "db_path": str(self.db_path),
            "conversations": count("conversations"),
            "messages": count("messages"),
            "council_sessions": count("council_sessions"),
            "council_messages": count("council_messages"),
            "traces": count("traces"),
            "agents": count("agent_genome"),
        }


# ── module-level singleton (lazy) ────────────────────────────────────────
_store: Optional[SessionStore] = None


def get_store() -> SessionStore:
    """Return the process-wide store, building it on first use."""
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


__all__ = ["SessionStore", "get_store", "default_db_path", "SCHEMA_VERSION"]
