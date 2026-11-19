from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest


def test_novamind_memory_adapters_close_schema_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from novamind import memory as legacy_memory
    from novamind.core import memory as core_memory
    from novamind.core.company.memory import CompanyMemory
    from novamind.core.company.reflective_rag import LocalVectorStore
    from novamind.core.company.registry import SoldierRegistry
    from novamind.core.memory_rag import SimpleRAG
    from novamind.memory.vector_store import VectorStore

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracked_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)

    legacy_memory.MemoryManager(str(tmp_path / "legacy-memory.db"))
    core_memory.MemoryManager(str(tmp_path / "core-memory.db"))
    SimpleRAG(str(tmp_path / "rag.db"))
    CompanyMemory(str(tmp_path / "company-memory.db"))
    SoldierRegistry(str(tmp_path / "registry.db"))
    LocalVectorStore(str(tmp_path / "reflective-rag.db"))
    VectorStore(tmp_path / "vectors.db")

    assert len(opened) >= 7
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
