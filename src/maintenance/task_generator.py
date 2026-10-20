"""Maintenance task generation — turn genome state into safe, LOW/MED work.

Stdlib-only, phone-safe. No LLM, no network: it maps an agent's genome fitness to
a candidate maintenance request that the orchestrator can run. This module is
PURE — it only PLANS; writing the ledger is the caller's job (see
``scripts/generate_tasks.py``), so a read-only route can never mutate state.

Design rule (non-negotiable): a generated task must NEVER classify as HIGH risk.
HIGH requests reach the council jury, and maintenance work is routine by
definition — so every template is written with LOW/MED keywords only
("review", "add test", "document", "explain", …), and ``generate_tasks`` filters
its own output through ``risk.classify`` as a last-line guard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..orchestrator.risk import RiskLevel, classify

#: Fitness below this marks an agent worth a revision task; at/above it the agent
#: is healthy enough for a lighter documentation/coverage task.
WEAK_FITNESS = 0.5

#: How many tasks one call produces by default, and the hard ceiling.
DEFAULT_LIMIT = 5
MAX_LIMIT = 10

#: (template, capability hint) per band. ``{agent}`` is substituted; the wording
#: is deliberately LOW/MED so ``risk.classify`` can never return HIGH.
_WEAK_TEMPLATES: Tuple[str, ...] = (
    "Review the {agent} agent's recent work and explain what can improve.",
    "List the weakest parts of the {agent} agent and describe each one.",
)
_MEDIUM_TEMPLATES: Tuple[str, ...] = (
    "Add test coverage for the {agent} agent's core behaviour.",
    "Add docstring and comment clarity to the {agent} agent's main module.",
)
_STRONG_TEMPLATES: Tuple[str, ...] = (
    "Explain how the {agent} agent works and describe its happy path.",
    "List what the {agent} agent does well and show an example.",
)


@dataclass(frozen=True)
class MaintenanceTask:
    """A single candidate maintenance request for one agent."""

    agent_id: str
    request: str
    risk: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "request": self.request,
            "risk": self.risk,
            "reason": self.reason,
        }


def _clamp_limit(limit: int) -> int:
    """Clamp a requested task count into ``1 .. MAX_LIMIT``."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if value < 1:
        return 1
    return min(value, MAX_LIMIT)


def _fitness_of(row: Mapping[str, Any]) -> Optional[float]:
    """Read a numeric fitness from a genome row, or ``None`` when unusable."""
    value = row.get("fitness")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _templates_for(fitness: Optional[float]) -> Tuple[str, ...]:
    """Pick the template band for a fitness (``None`` = treat as weak)."""
    if fitness is None or fitness < WEAK_FITNESS:
        return _WEAK_TEMPLATES
    if fitness < 0.75:
        return _MEDIUM_TEMPLATES
    return _STRONG_TEMPLATES


def _agent_id_of(row: Mapping[str, Any]) -> str:
    value = row.get("agent_id") or row.get("id") or ""
    return str(value).strip()


def task_for_agent(row: Mapping[str, Any]) -> Optional[MaintenanceTask]:
    """Build one maintenance task from a single genome row.

    Returns ``None`` when the row has no usable agent id — a nameless task would
    route to the wrong agent, so it is dropped rather than guessed.
    """
    agent_id = _agent_id_of(row)
    if not agent_id:
        return None
    fitness = _fitness_of(row)
    templates = _templates_for(fitness)
    request = templates[0].format(agent=agent_id)
    level = classify(request)
    reason = f"fitness={fitness if fitness is not None else 'unknown'}"
    return MaintenanceTask(
        agent_id=agent_id,
        request=request,
        risk=level.value,
        reason=reason,
    )


def _sort_key(row: Mapping[str, Any]) -> Tuple[int, float, str]:
    """Weakest (lowest fitness) first; unknown fitness treated as weakest."""
    fitness = _fitness_of(row)
    known = 0 if fitness is not None else -1
    return (known, fitness if fitness is not None else 0.0, _agent_id_of(row))


def generate_tasks(
    genome: Optional[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_LIMIT,
) -> List[MaintenanceTask]:
    """Turn a loaded genome document into ordered, LOW/MED maintenance tasks.

    ``genome`` is the parsed ``data/genome.json`` mapping (``{"agents": {...}}``).
    Agents with no fitness (or the weakest fitness) come first, so a bounded
    ``limit`` always spends itself on the agents that need attention most.

    A HIGH-risk task is impossible by construction, but each candidate is still
    filtered through ``risk.classify`` — a future template edit that sneaks a
    dangerous word in is dropped, never emitted.

    This function is PURE: it only PLANS and never writes the ledger. Recording
    belongs at the APPLIED boundary (``scripts/generate_tasks.py`` after a real
    ``/api/orchestrator/execute``), because the read-only route
    ``GET /api/maintenance/tasks`` calls this function — a ledger append here
    would let a plain GET mutate state and would double-count applied tasks.
    """
    rows = _rows_of(genome)
    ordered = sorted(rows, key=_sort_key)
    tasks: List[MaintenanceTask] = []
    for row in ordered:
        task = task_for_agent(row)
        if task is None:
            continue
        if task.risk == RiskLevel.HIGH.value:
            continue
        tasks.append(task)
        if len(tasks) >= _clamp_limit(limit):
            break
    return tasks


def _rows_of(genome: Optional[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Extract the agent rows from a genome document, tolerating junk."""
    if not isinstance(genome, Mapping):
        return []
    agents = genome.get("agents")
    if isinstance(agents, Mapping):
        rows: List[Mapping[str, Any]] = []
        for key, value in agents.items():
            if not isinstance(value, Mapping):
                continue
            row: Dict[str, Any] = dict(value)
            row.setdefault("agent_id", key)
            rows.append(row)
        return rows
    if isinstance(agents, Sequence) and not isinstance(agents, (str, bytes)):
        return [row for row in agents if isinstance(row, Mapping)]
    return []
