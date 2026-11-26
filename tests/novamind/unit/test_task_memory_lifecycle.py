from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from novamind.memory import task_memory


def _assert_connections_closed(connections: list[sqlite3.Connection]) -> None:
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_task_memory_closes_connections_for_every_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracked_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(task_memory.sqlite3, "connect", tracked_connect)
    memory = task_memory.TaskMemory(tmp_path / "tasks.db")

    result = SimpleNamespace(
        task_id="task-1",
        agent_id="agent-1",
        task_type="test",
        objective="verify cleanup",
        status="success",
        duration_seconds=1.25,
        output={"ok": True},
        error=None,
        finished_at="2026-11-19T00:00:00+00:00",
    )
    assert memory.save(result) is True
    assert memory.get("task-1")["agent_id"] == "agent-1"
    assert len(memory.recent()) == 1
    assert len(memory.by_agent("agent-1")) == 1
    assert memory.agent_stats()[0]["total_runs"] == 1
    assert memory.summary()["total_tasks"] == 1

    _assert_connections_closed(opened)


def test_task_memory_closes_connection_when_operation_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracked_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(task_memory.sqlite3, "connect", tracked_connect)
    memory = task_memory.TaskMemory(tmp_path / "exception.db")

    with pytest.raises(RuntimeError, match="simulated failure"):
        with memory._connect():
            raise RuntimeError("simulated failure")

    _assert_connections_closed(opened)
