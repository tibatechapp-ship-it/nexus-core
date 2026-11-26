"""Tests for SQLite persistence of lessons (Phase 4).

Uses in-memory databases (and ``tmp_path`` files) — no shared state, no network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
import json
from pathlib import Path

import pytest

from src.learning import (
    Lesson,
    LessonDatabase,
    LessonStore,
    Outcome,
    default_lesson_db_path,
)


@pytest.fixture()
def database_factory() -> Iterator[Callable[[str | Path], LessonDatabase]]:
    """Track every test database and close its connection during teardown."""
    databases: list[LessonDatabase] = []

    def create(path: str | Path = ":memory:") -> LessonDatabase:
        database = LessonDatabase(path)
        databases.append(database)
        return database

    try:
        yield create
    finally:
        for database in reversed(databases):
            database.close()


def make_lesson(
    *,
    lid: str = "id-1",
    principle: str = "When deploying, always run the tests",
    context: str = "deploy",
    confidence: float = 0.7,
    evidence: tuple[str, ...] = ("t1:s1",),
    source_outcome: Outcome = Outcome.FAILURE,
    created_at: float = 1.0,
    agent_role: str = "coder",
    tags: frozenset[str] = frozenset({"deploy"}),
) -> Lesson:
    return Lesson(
        id=lid,
        principle=principle,
        context=context,
        confidence=confidence,
        evidence=evidence,
        source_outcome=source_outcome,
        created_at=created_at,
        agent_role=agent_role,
        tags=tags,
    )


# ── schema ───────────────────────────────────────────────────────────────
def test_migrate_creates_table_and_sets_version(database_factory):
    db = database_factory(":memory:")
    assert db.count() == 0
    version = db.connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1


def test_migrate_schema_is_idempotent(database_factory):
    db = database_factory(":memory:")
    db.migrate_schema()
    db.migrate_schema()
    assert db.count() == 0


def test_lesson_database_close_is_idempotent(database_factory):
    db = database_factory()
    db.close()
    db.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        db.count()


def test_lesson_database_context_manager_closes_connection(database_factory):
    db = database_factory()
    with db as managed:
        assert managed.count() == 0
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        db.count()


# ── round trip ───────────────────────────────────────────────────────────
def test_save_then_load_round_trips_every_field(database_factory):
    db = database_factory(":memory:")
    lesson = make_lesson(evidence=("a:1", "a:2"), tags=frozenset({"x", "y"}))
    assert db.save([lesson]) == 1

    loaded = db.load()
    assert loaded == [lesson]


def test_load_is_newest_first(database_factory):
    db = database_factory(":memory:")
    db.save(
        [
            make_lesson(lid="old", created_at=1.0),
            make_lesson(lid="new", created_at=3.0),
            make_lesson(lid="mid", created_at=2.0),
        ]
    )
    assert [lesson.id for lesson in db.load()] == ["new", "mid", "old"]


def test_save_upserts_same_id(database_factory):
    db = database_factory(":memory:")
    db.save([make_lesson(lid="a", confidence=0.4)])
    db.save([make_lesson(lid="a", confidence=0.9)])

    assert db.count() == 1
    assert db.load()[0].confidence == pytest.approx(0.9)


def test_load_skips_malformed_rows(database_factory):
    db = database_factory(":memory:")
    db.save([make_lesson(lid="good")])
    db.connection.execute(
        "INSERT INTO lessons (id, principle, source_outcome) VALUES (?, ?, ?)",
        ("bad", "boom", "EXPLODED"),
    )
    db.connection.commit()

    loaded = db.load()
    assert [lesson.id for lesson in loaded] == ["good"]


def test_persists_across_connections(tmp_path, database_factory):
    path = tmp_path / "lessons.db"
    first = database_factory(path)
    first.save([make_lesson(lid="a")])
    first.close()

    second = database_factory(path)
    assert second.count() == 1
    assert second.load()[0].id == "a"
    second.close()


def test_clear_and_count(database_factory):
    db = database_factory(":memory:")
    db.save([make_lesson(lid="a"), make_lesson(lid="b")])
    assert db.count() == 2
    db.clear()
    assert db.count() == 0


# ── store <-> db ─────────────────────────────────────────────────────────
def test_store_save_to_and_load_from_db(database_factory):
    db = database_factory(":memory:")
    store = LessonStore(database=db)
    store.add(make_lesson(lid="a", confidence=0.8))

    assert store.save_to_db() == 1
    assert db.count() == 1

    restored = LessonStore(database=db)
    assert restored.load_from_db() == 1
    assert restored.get("a") == store.get("a")


def test_store_database_property_and_migrate(database_factory):
    db = database_factory(":memory:")
    store = LessonStore(database=db)
    assert store.database is db
    store.migrate_schema()


def test_store_methods_accept_explicit_database(database_factory):
    db = database_factory(":memory:")
    store = LessonStore()  # no database configured
    store.add(make_lesson(lid="a"))

    assert store.save_to_db(db) == 1
    other = LessonStore()
    assert other.load_from_db(db) == 1


def test_store_requires_a_database():
    store = LessonStore()
    with pytest.raises(ValueError):
        store.save_to_db()
    with pytest.raises(ValueError):
        store.load_from_db()
    with pytest.raises(ValueError):
        store.migrate_schema()


# ── default path ─────────────────────────────────────────────────────────
def test_default_lesson_db_path_uses_env(monkeypatch):
    monkeypatch.setenv("ZYVO_LESSON_DB", "/tmp/custom-lessons.db")
    assert str(default_lesson_db_path()) == "/tmp/custom-lessons.db"


def test_default_lesson_db_path_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("ZYVO_LESSON_DB", raising=False)
    path = default_lesson_db_path()
    assert path.name == "lessons.db"
    assert "tyb-zyv-ai" in str(path)


def test_saved_row_stores_json_encoded_evidence_and_tags(database_factory):
    db = database_factory(":memory:")
    db.save([make_lesson(lid="a", evidence=("t:1",), tags=frozenset({"z", "a"}))])
    row = db.connection.execute("SELECT evidence, tags FROM lessons WHERE id='a'").fetchone()
    assert json.loads(row["evidence"]) == ["t:1"]
    assert json.loads(row["tags"]) == ["a", "z"]
