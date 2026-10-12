"""Tool runs view — the execution traces of tool-using agent runs.

When agents run with a :class:`~src.tools.executor.ToolPolicy` each stage emits a
:class:`~src.tools.executor.ToolRun` (the tool calls it made and their results).
This modal flattens every trace into one table so you can see exactly which tool
fired, whether it succeeded, and what it returned.
"""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static

from src.tools.executor import ToolOutcome, ToolRun
from src.tui.screens.base import ModalBase

__all__ = ["ToolRunsScreen"]

_MAX_RESULT_CHARS = 80


class ToolRunsScreen(ModalBase):
    """A modal table of every tool call made by tool-enabled runs."""

    title_text = "Tool runs — execution traces"

    def compose(self) -> ComposeResult:
        with Vertical(id="toolruns-modal"):
            yield Label(self.title_text, classes="modal-title")
            yield Static(self.summary_text(), id="toolruns-summary")
            yield Static(self.build_table(), id="toolruns-body")
            yield Label("press esc to close", classes="modal-hint")

    # -- data --------------------------------------------------------------
    def visible_runs(self) -> list[ToolRun]:
        """Every tool run recorded by the app's :class:`TuiState`."""
        return list(self.zyvo.state.tool_runs)

    def _flatten(self) -> list[tuple[str, int, ToolOutcome]]:
        """Return ``(agent, call_index, outcome)`` for every tool call, in order."""
        rows: list[tuple[str, int, ToolOutcome]] = []
        for run in self.visible_runs():
            for index, outcome in enumerate(run.outcomes, start=1):
                rows.append((run.result.agent, index, outcome))
        return rows

    def summary_text(self) -> str:
        """One-line summary: runs, tool calls and failures."""
        runs = self.visible_runs()
        calls = self._flatten()
        failures = sum(1 for _, _, outcome in calls if not outcome.ok)
        if not runs:
            return "no tool runs recorded — pass a ToolPolicy to run agents with tools"
        return (
            f"{len(runs)} run(s) · {len(calls)} tool call(s) · {failures} failed"
        )

    # -- rendering ---------------------------------------------------------
    def build_table(self) -> Table:
        """Build the flat table of tool calls for the current traces."""
        table = Table(expand=True)
        table.add_column("Agent")
        table.add_column("#", justify="right")
        table.add_column("Tool")
        table.add_column("OK")
        table.add_column("Result", overflow="fold")

        rows = self._flatten()
        if not rows:
            table.add_row("", "", Text("(no tool calls yet)", style="dim"), "", "")
            return table

        for agent, index, outcome in rows:
            ok = Text("ok", style="green") if outcome.ok else Text("fail", style="red")
            body = outcome.output if outcome.ok else (outcome.error or "error")
            table.add_row(agent, str(index), outcome.name, ok, _truncate(body))
        return table


def _truncate(text: str) -> str:
    """Collapse whitespace and clamp ``text`` for a table cell."""
    flat = " ".join(text.split())
    if len(flat) <= _MAX_RESULT_CHARS:
        return flat
    return flat[: _MAX_RESULT_CHARS - 1] + "…"
