from __future__ import annotations

import gc
import sqlite3
import weakref

import pytest

from src.ops.store import OpsStore
from src.org.store import OrgStore


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
