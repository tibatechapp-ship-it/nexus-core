"""Tests for the maintenance task generator (pure, stdlib-only)."""
from __future__ import annotations

from src.maintenance.task_generator import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    WEAK_FITNESS,
    MaintenanceTask,
    _clamp_limit,
    _fitness_of,
    _templates_for,
    generate_tasks,
    task_for_agent,
)


def _row(agent_id: str, fitness: object = 0.6) -> dict:
    return {"agent_id": agent_id, "fitness": fitness}


# ─── fitness parsing ────────────────────────────────────────────────────────
def test_fitness_of_reads_numbers() -> None:
    assert _fitness_of({"fitness": 0.75}) == 0.75
    assert _fitness_of({"fitness": 1}) == 1.0


def test_fitness_of_rejects_bool_and_junk() -> None:
    assert _fitness_of({"fitness": True}) is None
    assert _fitness_of({"fitness": False}) is None
    assert _fitness_of({"fitness": "high"}) is None
    assert _fitness_of({}) is None


# ─── template bands ─────────────────────────────────────────────────────────
def test_templates_weak_for_low_and_unknown() -> None:
    assert _templates_for(0.2) == _templates_for(None)
    assert _templates_for(WEAK_FITNESS - 0.01)[0].startswith("Review")


def test_templates_medium_band() -> None:
    assert "Add test coverage" in _templates_for(0.6)[0]


def test_templates_strong_band() -> None:
    assert _templates_for(0.9)[0].startswith("Explain")


# ─── limit clamping ─────────────────────────────────────────────────────────
def test_clamp_limit_bounds() -> None:
    assert _clamp_limit(0) == 1
    assert _clamp_limit(-5) == 1
    assert _clamp_limit(3) == 3
    assert _clamp_limit(999) == MAX_LIMIT


def test_clamp_limit_junk_is_default() -> None:
    assert _clamp_limit(None) == DEFAULT_LIMIT  # type: ignore[arg-type]
    assert _clamp_limit("nope") == DEFAULT_LIMIT  # type: ignore[arg-type]


# ─── single task ────────────────────────────────────────────────────────────
def test_task_for_agent_never_high() -> None:
    task = task_for_agent(_row("coder", 0.1))
    assert isinstance(task, MaintenanceTask)
    assert task.risk in ("low", "med")
    assert task.agent_id == "coder"
    assert "coder" in task.request


def test_task_for_agent_without_id_is_dropped() -> None:
    assert task_for_agent({"fitness": 0.5}) is None
    assert task_for_agent({"agent_id": "   ", "fitness": 0.5}) is None


def test_task_for_agent_reads_id_or_id_key() -> None:
    assert task_for_agent({"id": "analyst", "fitness": 0.9}) is not None


def test_task_to_dict_shape() -> None:
    task = task_for_agent(_row("devops", 0.8))
    assert task is not None
    payload = task.to_dict()
    assert set(payload) == {"agent_id", "request", "risk", "reason"}


# ─── full generation ────────────────────────────────────────────────────────
def test_generate_tasks_orders_weakest_first() -> None:
    genome = {
        "agents": {
            "strong": {"fitness": 0.9},
            "weak": {"fitness": 0.1},
            "unknown": {"fitness": None},
        }
    }
    tasks = generate_tasks(genome, limit=3)
    # unknown fitness is treated as weakest → first; weak second; strong last.
    assert [t.agent_id for t in tasks] == ["unknown", "weak", "strong"]


def test_generate_tasks_respects_limit() -> None:
    genome = {"agents": {f"a{i}": {"fitness": 0.5} for i in range(20)}}
    assert len(generate_tasks(genome, limit=3)) == 3
    assert len(generate_tasks(genome)) == DEFAULT_LIMIT


def test_generate_tasks_never_emits_high() -> None:
    genome = {"agents": {f"a{i}": {"fitness": i / 10} for i in range(10)}}
    tasks = generate_tasks(genome, limit=10)
    assert tasks
    assert all(t.risk != "high" for t in tasks)


def test_generate_tasks_tolerates_junk_genome() -> None:
    assert generate_tasks(None) == []
    assert generate_tasks({}) == []
    assert generate_tasks({"agents": "not a mapping"}) == []
    assert generate_tasks({"agents": [{"agent_id": "x", "fitness": 0.5}]}) != []


def test_generate_tasks_skips_non_mapping_rows() -> None:
    genome = {"agents": {"good": {"fitness": 0.5}, "bad": "junk"}}
    tasks = generate_tasks(genome)
    assert [t.agent_id for t in tasks] == ["good"]


def test_generate_tasks_skips_nameless_rows() -> None:
    """A mapping row with no usable id yields no task and is skipped."""
    genome = {"agents": {"": {"fitness": 0.5}, "good": {"fitness": 0.5}}}
    tasks = generate_tasks(genome)
    assert [t.agent_id for t in tasks] == ["good"]


def test_generate_tasks_high_guard_drops_candidate(monkeypatch) -> None:
    """A future template that sneaks a dangerous word in is dropped, not sent."""
    import src.maintenance.task_generator as tg

    def fake_classify(_text: str) -> object:
        return tg.RiskLevel.HIGH

    monkeypatch.setattr(tg, "classify", fake_classify)
    genome = {"agents": {"coder": {"fitness": 0.5}}}
    assert generate_tasks(genome) == []
