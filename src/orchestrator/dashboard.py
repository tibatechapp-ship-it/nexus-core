"""Orchestrator dashboard — read-only CLI over ``_metrics.py``.

Run it after some executions::

    python -m src.orchestrator.dashboard

It prints the numbers that decide the next feature: how often requests were
decomposed, which agents run and fail, the real risk mix, and how often the
jury fired. Reporting is pure aggregation over the recorded log, so it can be
tested without a filesystem.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any, Mapping

from ._metrics import load

_RISKS = ("low", "med", "high")


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate raw execution records into the dashboard counters.

    Pure: takes the list of records (as returned by ``_metrics.load``) and
    returns a flat dict. Always returns a complete shape, even for ``[]``.
    """
    total = len(rows)
    risk_counts = {level: 0 for level in _RISKS}
    agent_runs: dict[str, int] = {}
    agent_failures: dict[str, int] = {}
    decomposed = 0
    single = 0
    failed_runs = 0
    jury = 0
    subtask_total = 0

    for row in rows:
        level = str(row.get("risk", "low"))
        if level in risk_counts:
            risk_counts[level] += 1
        if row.get("decomposed"):
            decomposed += 1
        else:
            single += 1
        if not row.get("ok", True):
            failed_runs += 1
        if row.get("jury_fired"):
            jury += 1
        for agent in row.get("agents", []) or []:
            agent_runs[str(agent)] = agent_runs.get(str(agent), 0) + 1
        for agent in row.get("failed_agents", []) or []:
            agent_failures[str(agent)] = agent_failures.get(str(agent), 0) + 1
        n = row.get("n_subtasks")
        if isinstance(n, int) and n > 0:
            subtask_total += n

    top_agents = sorted(agent_runs.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    failure_rates = {
        agent: (agent_failures.get(agent, 0) / count if count else 0.0)
        for agent, count in agent_runs.items()
        if agent_failures.get(agent, 0) > 0
    }
    avg_subtasks = (subtask_total / total) if total else 0.0

    return {
        "total": total,
        "decomposed": decomposed,
        "single": single,
        "decomposed_ratio": (decomposed / total) if total else 0.0,
        "risk": risk_counts,
        "high_ratio": (risk_counts["high"] / total) if total else 0.0,
        "failed_runs": failed_runs,
        "run_failure_rate": (failed_runs / total) if total else 0.0,
        "jury_fired": jury,
        "jury_rate": (jury / total) if total else 0.0,
        "top_agents": top_agents,
        "failure_rates": failure_rates,
        "avg_subtasks": avg_subtasks,
    }


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render(summary: Mapping[str, Any]) -> str:
    """Render a summary as a plain-text table block."""
    lines = [
        "═══ Orchestrator Dashboard ═══",
        f"executions        : {summary['total']}",
        f"decomposed        : {summary['decomposed']}  ({_pct(summary['decomposed_ratio'])})",
        f"single            : {summary['single']}",
        f"avg subtasks/req  : {summary['avg_subtasks']:.2f}",
        "─── risk ───",
        f"low / med / high: {summary['risk']['low']} / {summary['risk']['med']} / {summary['risk']['high']}"
        f"   (high {_pct(summary['high_ratio'])})",
        "─── jury ───",
        f"jury fired        : {summary['jury_fired']}  ({_pct(summary['jury_rate'])})",
        "─── agents (top 5 by executions) ───",
    ]
    if summary["top_agents"]:
        for agent, count in summary["top_agents"]:
            rate = summary["failure_rates"].get(agent, 0.0)
            lines.append(f"  {agent:<18} runs={count:<4} fail={_pct(rate)}")
    else:
        lines.append("  (no executions recorded yet)")
    lines.append("─── runs failing: {}  ({}) ───".format(
        summary["failed_runs"], _pct(summary["run_failure_rate"])))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``python -m src.orchestrator.dashboard``."""
    _ = argv
    print(render(summarize(load())))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
