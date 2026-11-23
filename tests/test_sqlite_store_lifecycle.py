from __future__ import annotations

import gc
import sqlite3
import weakref

import pytest

from src.ops.store import OpsStore
from src.org.store import OrgStore
from src.learning.lesson_store import LessonDatabase
from src.learning.interactions import (
    InteractionStore,
    get_interaction_store,
    reset_interaction_store,
)


@pytest.mark.parametrize(
    ("store_type", "raw_connection"),
    [
        (OpsStore, lambda store: store._conn._raw),
        (OrgStore, lambda store: store._conn._conn),
    ],
)
def test_store_close_releases_sqlite_connection(store_type, raw_connection) -> None:
    store = store_type(":memory:")
    connection = raw_connection(store)

    store.close()
    store.close()  # close is idempotent

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


@pytest.mark.parametrize(
    ("store_type", "raw_connection"),
    [
        (OpsStore, lambda store: store._conn._raw),
        (OrgStore, lambda store: store._conn._conn),
    ],
)
def test_store_context_manager_closes_connection(store_type, raw_connection) -> None:
    with store_type(":memory:") as store:
        connection = raw_connection(store)
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


@pytest.mark.parametrize(
    ("store_type", "raw_connection"),
    [
        (OpsStore, lambda store: store._conn._raw),
        (OrgStore, lambda store: store._conn._conn),
    ],
)
def test_store_finalizer_is_a_last_resort_cleanup(store_type, raw_connection) -> None:
    store = store_type(":memory:")
    connection = raw_connection(store)
    store_ref = weakref.ref(store)

    del store
    gc.collect()

    assert store_ref() is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

def test_lesson_database_close_and_finalizer_release_connection(tmp_path) -> None:
    database = LessonDatabase(tmp_path / "lessons.db")
    connection = database.connection
    database.close()
    database.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    database = LessonDatabase(tmp_path / "lessons-finalizer.db")
    connection = database.connection
    database_ref = weakref.ref(database)
    del database
    gc.collect()
    assert database_ref() is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_interaction_store_close_and_finalizer_release_connection(tmp_path) -> None:
    store = InteractionStore(str(tmp_path / "interactions.db"))
    connection = store._conn
    store.close()
    store.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    store = InteractionStore(str(tmp_path / "interactions-finalizer.db"))
    connection = store._conn
    store_ref = weakref.ref(store)
    del store
    gc.collect()
    assert store_ref() is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_reset_interaction_singleton_closes_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NEXUS_INTERACTIONS_DB", str(tmp_path / "singleton.db"))
    reset_interaction_store()
    store = get_interaction_store()
    connection = store._conn
    reset_interaction_store()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
