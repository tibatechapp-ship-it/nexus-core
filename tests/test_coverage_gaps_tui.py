"""Coverage-gap tests for ``src.tui``.

These exercise the branches the main TUI suite (``tests/test_src_tui.py``)
never reaches: an empty command submit, a task that performed tool calls seen
through the *dashboard* path, the no-agents default-task guard, tables rendered
with real rows, the defensive guards on foreign button ids / out-of-range row
keys, a metrics panel refreshed without a fresh call count, and a snapshot with
no memory but a battery. Helpers are reused from the main suite on purpose —
one fake, one home.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Input, RichLog

from src.agents.registry import AgentRegistry
from src.core import sysinfo
from src.core.backend import EchoBackend
from src.tools.executor import ToolPolicy
from src.tui.app import ZyvoTUI
from src.tui.screens.logs import LogsScreen
from src.tui.screens.security import SecurityScreen
from src.tui.screens.tasks import TasksScreen
from src.tui.state import TuiState
from src.tui.widgets.metrics import MetricsPanel
from tests.test_src_tui import _ToolAgent, _ToolBackend, _registry


def _app(registry: AgentRegistry | None = None, backend: Any = None) -> ZyvoTUI:
    return ZyvoTUI(registry=registry if registry is not None else _registry(), backend=backend or EchoBackend())


def _transcript(app: ZyvoTUI) -> list[str]:
    """The dashboard's conversation log as plain text, one string per line."""

    log = app.screen.query_one("#log", RichLog)
    return [line.text for line in log.lines]


# ── state: bare construction ─────────────────────────────────────────────
def test_state_without_registry_or_backend_is_empty() -> None:
    """With neither a registry nor a backend the state starts empty."""

    state = TuiState()
    assert state.registry.names() == []
    assert state.backend is None


# ── app: quit binding ────────────────────────────────────────────────────
def test_action_quit_exits_the_app() -> None:
    """``action_quit`` (the ctrl+c binding) must stop the app."""

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.action_quit()

    asyncio.run(scenario())


# ── metrics panel ────────────────────────────────────────────────────────
def test_metrics_refresh_panel_keeps_count_when_none() -> None:
    """``refresh_panel()`` with no argument must keep the previous count."""

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.action_show_monitor()
            await pilot.pause()
            panel = app.screen.query_one(MetricsPanel)
            before = panel._llm_calls
            panel.refresh_panel()
            assert panel._llm_calls == before == 0

    asyncio.run(scenario())


def test_metrics_table_without_memory_but_with_battery(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host with no ``/proc/meminfo`` but a battery skips memory, shows battery."""

    monkeypatch.setattr(
        sysinfo,
        "snapshot",
        lambda: {
            "cpu_count": 4,
            "load_average": (),
            "memory": None,
            "battery": {"percent": 88, "status": "Charging", "name": "battery"},
            "uptime": 7200.0,
        },
    )
    table = MetricsPanel(llm_calls=2).build_table()
    headers = [str(column.header) for column in table.columns]
    assert "Metric" in headers and "Value" in headers
    # cpu + load + battery + uptime + llm calls = 5 rows (no memory row).
    assert table.row_count == 5


def test_metrics_table_without_battery(monkeypatch: pytest.MonkeyPatch) -> None:
    """A desktop host with memory but no battery skips the battery row."""

    monkeypatch.setattr(
        sysinfo,
        "snapshot",
        lambda: {
            "cpu_count": 8,
            "load_average": (0.5, 0.4, 0.3),
            "memory": {"used_kb": 2048, "total_kb": 8192, "used_percent": 25},
            "battery": None,
            "uptime": 60.0,
        },
    )
    table = MetricsPanel(llm_calls=0).build_table()
    assert table.row_count == 5


# ── dashboard ────────────────────────────────────────────────────────────
def test_dashboard_ignores_blank_submit() -> None:
    """A whitespace-only submit is a no-op (early return in the handler)."""

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            lines_before = len(_transcript(app))
            box = app.screen.query_one("#command", Input)
            box.value = "   "
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.tasks == []
            assert len(_transcript(app)) == lines_before

    asyncio.run(scenario())


def test_dashboard_reports_tool_calls(tmp_path: Path) -> None:
    """A task that used tools logs the 'tool call(s)' hint (dashboard path)."""

    backend = _ToolBackend('<tool-call name="read" args=\'{"path": "note.txt"}\'/>', "answer")
    registry = AgentRegistry([_ToolAgent(backend)])
    app = ZyvoTUI(registry=registry, backend=backend)
    app.state.tool_policy = ToolPolicy(root=tmp_path)
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")

    async def scenario() -> None:
        async with app.run_test() as pilot:
            box = app.screen.query_one("#command", Input)
            box.value = "@tool look"
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.tasks[-1].tool_calls >= 1
            assert any("tool call(s)" in line for line in _transcript(app))

    asyncio.run(scenario())


def test_dashboard_default_task_with_no_agents() -> None:
    """With an empty registry a plain task is refused with a hint."""

    app = ZyvoTUI(registry=AgentRegistry(), backend=EchoBackend())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            box = app.screen.query_one("#command", Input)
            box.value = "hello there"
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.tasks == []
            assert "No agents registered" in _transcript(app)[-1]

    asyncio.run(scenario())


# ── logs / tasks tables with real rows ───────────────────────────────────
def test_logs_and_tasks_tables_render_rows() -> None:
    """Both views must render one row per entry and honour level filtering."""

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.state.add_log("info", "hello world")
            app.state.add_log("warn", "careful now")
            app.state.run_agent("echo", "hi")

            app.action_show_logs()
            await pilot.pause()
            assert isinstance(app.screen, LogsScreen)
            expected = app.state.filtered_logs()
            assert len(expected) > 2  # the two seeded rows plus the run's own logs
            assert app.screen.build_table().row_count == len(expected)
            app.screen.action_set_level("info")
            assert app.screen.build_table().row_count == len(app.state.filtered_logs(level="INFO"))
            app.screen._query = "nothing matches this"
            assert app.screen.build_table().row_count == 1  # "(no log entries)" row

            app.action_show_tasks()
            await pilot.pause()
            assert isinstance(app.screen, TasksScreen)
            assert app.screen.build_table().row_count == 1

    asyncio.run(scenario())


# ── security screen: defensive guards ────────────────────────────────────
def test_security_screen_ignores_foreign_button_and_row() -> None:
    """An unknown button id and an out-of-range row key are both ignored."""

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.action_show_security()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SecurityScreen)

            foreign = SimpleNamespace(button=SimpleNamespace(id="btn-unknown"))
            screen.on_button_pressed(foreign)  # type: ignore[arg-type]
            assert screen._report is None  # nothing ran

            out_of_range = SimpleNamespace(row_key=SimpleNamespace(value="999"))
            screen.on_data_table_row_highlighted(out_of_range)  # type: ignore[arg-type]

    asyncio.run(scenario())
