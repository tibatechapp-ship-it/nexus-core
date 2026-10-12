"""Tests for the v1.5 SQLite conversation store.

The store is pure stdlib, so these run in the phone framework gate as well as
in CI (no ``novamind`` extras required).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.novamind.core.session_store import (
    SCHEMA_VERSION,
    SessionStore,
    default_db_path,
)


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.db")


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {r[0] for r in rows}


def test_schema_creates_all_tables(store: SessionStore) -> None:
    tables = _tables(store.db_path)
    assert {"conversations", "messages", "council_sessions", "council_messages",
            "traces"} <= tables


def test_schema_version_is_recorded(store: SessionStore) -> None:
    with sqlite3.connect(store.db_path) as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    assert version == SCHEMA_VERSION


def test_default_db_path_honours_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom.db"
    monkeypatch.setenv("NEXUS_DB", str(target))
    assert default_db_path() == target


def test_create_and_get_conversation(store: SessionStore) -> None:
    conv = store.create_conversation(title="hello", agent="coder")
    assert conv["id"]
    fetched = store.get_conversation(conv["id"])
    assert fetched is not None
    assert fetched["title"] == "hello"
    assert fetched["messages"] == []


def test_get_missing_conversation_returns_none(store: SessionStore) -> None:
    assert store.get_conversation("does-not-exist") is None


def test_add_message_and_list_preview(store: SessionStore) -> None:
    conv = store.create_conversation(title="t")
    store.add_message(conv["id"], "user", "first")
    store.add_message(conv["id"], "assistant", "second")
    listed = store.list_conversations()
    assert len(listed) == 1
    assert listed[0]["message_count"] == 2
    assert listed[0]["preview"] == "second"


def test_created_conversation_id_is_used(store: SessionStore) -> None:
    conv = store.create_conversation(conv_id="fixed-id", title="x")
    assert conv["id"] == "fixed-id"
    assert store.get_conversation("fixed-id") is not None


def test_update_conversation_renames_and_reorders(store: SessionStore) -> None:
    a = store.create_conversation(title="a")
    b = store.create_conversation(title="b")
    assert store.update_conversation(a["id"], title="A2") is True
    assert store.get_conversation(a["id"])["title"] == "A2"
    # a was updated last → sorts first
    assert store.list_conversations()[0]["id"] == a["id"]
    assert store.update_conversation("nope", title="x") is False
    assert b["id"]


def test_update_with_no_fields_returns_false(store: SessionStore) -> None:
    conv = store.create_conversation()
    assert store.update_conversation(conv["id"]) is False


def test_delete_conversation_cascades_messages(store: SessionStore) -> None:
    conv = store.create_conversation()
    store.add_message(conv["id"], "user", "hi")
    assert store.delete_conversation(conv["id"]) is True
    assert store.get_conversation(conv["id"]) is None
    assert store.stats()["messages"] == 0


def test_clear_conversations(store: SessionStore) -> None:
    for _ in range(3):
        store.create_conversation()
    assert store.clear_conversations() == 3
    assert store.stats()["conversations"] == 0


def test_replace_messages_overwrites_thread(store: SessionStore) -> None:
    conv = store.create_conversation()
    store.add_message(conv["id"], "user", "old")
    n = store.replace_messages(conv["id"], [
        {"role": "user", "content": "new1", "ts": 10},
        {"role": "assistant", "content": "new2", "ts": 11},
    ])
    assert n == 2
    msgs = store.get_conversation(conv["id"])["messages"]
    assert [m["content"] for m in msgs] == ["new1", "new2"]


def test_truncate_from_removes_tail(store: SessionStore) -> None:
    conv = store.create_conversation()
    store.add_message(conv["id"], "user", "a", ts=100)
    store.add_message(conv["id"], "assistant", "b", ts=200)
    removed = store.truncate_from(conv["id"], 150)
    assert removed == 1
    assert [m["content"] for m in store.get_conversation(conv["id"])["messages"]] == ["a"]


def test_search_matches_title_and_content(store: SessionStore) -> None:
    c1 = store.create_conversation(title="python tips")
    c2 = store.create_conversation(title="other")
    store.add_message(c2["id"], "user", "كيف أستخدم python؟")
    by_title = store.search_conversations("python")
    assert {c["id"] for c in by_title} == {c1["id"], c2["id"]}
    assert store.search_conversations("zzz-none") == []


def test_export_json_roundtrips(store: SessionStore) -> None:
    conv = store.create_conversation(title="exp")
    store.add_message(conv["id"], "user", "hello")
    raw = store.export_conversation(conv["id"], "json")
    assert raw is not None
    data = json.loads(raw)
    assert data["title"] == "exp"
    assert data["messages"][0]["content"] == "hello"


def test_export_markdown_contains_roles(store: SessionStore) -> None:
    conv = store.create_conversation(title="md")
    store.add_message(conv["id"], "user", "q")
    store.add_message(conv["id"], "assistant", "a")
    md = store.export_conversation(conv["id"], "markdown")
    assert md is not None
    assert "# md" in md
    assert "👤 user" in md and "🤖 assistant" in md


def test_export_missing_returns_none(store: SessionStore) -> None:
    assert store.export_conversation("nope") is None


def test_import_localstorage_payload_is_idempotent(store: SessionStore) -> None:
    payload = [{
        "id": "old1", "title": "قديم",
        "messages": [{"role": "user", "content": "x", "ts": 5}],
    }]
    assert store.import_conversations(payload) == 1
    assert store.import_conversations(payload) == 0  # second time = no-op
    assert store.stats()["messages"] == 1


def test_council_session_roundtrip(store: SessionStore) -> None:
    sess = store.create_council_session("topic", rounds=3)
    store.add_council_message(sess["id"], 1, "analyst", "رأي")
    got = store.get_council_session(sess["id"])
    assert got is not None
    assert got["messages"][0]["agent"] == "analyst"
    assert store.update_council_session(sess["id"], status="done", consensus=0.8) is True
    assert store.get_council_session(sess["id"])["status"] == "done"


def test_stats_snapshot(store: SessionStore) -> None:
    store.create_conversation()
    stats = store.stats()
    assert stats["conversations"] == 1
    assert set(stats) >= {"db_path", "messages", "council_sessions", "council_messages"}


# ── time machine (traces) ────────────────────────────────────────────────
def test_add_and_get_trace(store: SessionStore) -> None:
    tr = store.add_trace("c1", "ping", "pong", agent="coder", status="ok",
                         latency_ms=42, plan={"category": "code"},
                         gatekeeper={"decision": "allow"}, pre_check={"decision": "clean"})
    assert tr["id"]
    got = store.get_trace(tr["id"])
    assert got is not None
    assert got["message"] == "ping"
    assert got["response"] == "pong"
    assert got["latency_ms"] == 42
    assert got["plan"]["category"] == "code"
    assert got["gatekeeper"]["decision"] == "allow"
    assert got["pre_check"]["decision"] == "clean"


def test_get_missing_trace_returns_none(store: SessionStore) -> None:
    assert store.get_trace("nope") is None


def test_list_traces_filters_by_conversation(store: SessionStore) -> None:
    store.add_trace("c1", "a", "A", ts=100)
    store.add_trace("c1", "b", "B", ts=200)
    store.add_trace("c2", "c", "C", ts=300)
    assert len(store.list_traces()) == 3
    c1 = store.list_traces("c1")
    assert [t["message"] for t in c1] == ["b", "a"]  # newest first
    assert store.list_traces("c1", newest_first=False)[0]["message"] == "a"


def test_search_traces(store: SessionStore) -> None:
    store.add_trace("c1", "deploy the service", "ok", agent="ops")
    store.add_trace("c1", "hello world", "hi", agent="coder")
    assert len(store.search_traces("deploy")) == 1
    assert len(store.search_traces("ops")) == 1
    assert store.search_traces("zzz-nope") == []


def test_delete_and_clear_traces(store: SessionStore) -> None:
    t1 = store.add_trace("c1", "a", "A")
    store.add_trace("c2", "b", "B")
    assert store.delete_trace(t1["id"]) is True
    assert store.delete_trace(t1["id"]) is False
    assert store.clear_traces("c2") == 1
    store.add_trace("c3", "c", "C")
    assert store.clear_traces() == 1
    assert store.stats()["traces"] == 0


def test_export_trace_json_and_markdown(store: SessionStore) -> None:
    tr = store.add_trace("c1", "issue", "solution", agent="coder", latency_ms=7)
    raw = store.export_trace(tr["id"], "json")
    assert raw is not None
    assert json.loads(raw)["message"] == "issue"
    md = store.export_trace(tr["id"], "markdown")
    assert md is not None
    assert "Time Machine" in md and "issue" in md and "solution" in md
    assert store.export_trace("nope") is None


def test_trace_json_field_coercion(store: SessionStore) -> None:
    # a JSON string passes through, a plain string is wrapped, None → {}
    tr = store.add_trace("c1", "m", "r",
                         plan='{"a": 1}', gatekeeper="not json", pre_check=None)
    got = store.get_trace(tr["id"])
    assert got["plan"] == {"a": 1}
    assert got["gatekeeper"] == {"text": "not json"}
    assert got["pre_check"] == {}


def test_trace_counted_in_stats(store: SessionStore) -> None:
    store.add_trace("c1", "m", "r")
    assert store.stats()["traces"] == 1
