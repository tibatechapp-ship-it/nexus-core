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


# ─── metrics surface (FastAPI) ──────────────────────────────────────────────
def _api_client():
    """A TestClient whose app is mounted, mirroring the gateway layout."""
    import pytest

    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.maintenance.api import build_router

    child = FastAPI()
    child.router.routes.extend(build_router().routes)
    parent = FastAPI()
    parent.mount("/", child)
    return TestClient(parent), child, FastAPI, build_router


class _FakeGenome:
    """Minimal genome stand-in exposing stats() + to_dict()."""

    def stats(self) -> dict:
        return {"agents": 3, "active": 2, "retired": 1, "observations": 7}

    def to_dict(self) -> dict:
        return {"agents": {"coder": {"fitness": 0.2}, "tester": {"fitness": 0.9}}}


def test_metrics_snapshot_shape_and_zeros() -> None:
    from src.maintenance.api import metrics_snapshot

    payload = metrics_snapshot(fitness=_FakeGenome())
    assert payload["ok"] is True
    assert payload["scope"] == "maintenance"
    assert payload["genome"]["agents"] == 3
    assert payload["genome"]["observations"] == 7
    # The priority breakdown is a stable shape with zero values for now.
    assert payload["by_priority"] == {"low": 0, "medium": 0, "high": 0}


def test_metrics_snapshot_tolerates_a_broken_genome() -> None:
    from src.maintenance.api import metrics_snapshot

    class _Broken:
        def stats(self) -> dict:
            raise RuntimeError("boom")

    payload = metrics_snapshot(fitness=_Broken())
    assert payload["ok"] is True
    assert payload["genome"]["agents"] == 0


def test_metrics_route_survives_an_asgi_mount() -> None:
    """The routes must be reachable through a mount (deferred-router guard)."""
    client, _child, _FastAPI, _build = _api_client()
    resp = client.get("/api/maintenance/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["scope"] == "maintenance"


def test_tasks_route_reports_ok_and_a_list() -> None:
    client, _child, _FastAPI, _build = _api_client()
    resp = client.get("/api/maintenance/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["tasks"], list)


def test_register_extends_concrete_routes() -> None:
    """register() must extend real paths, never a deferred placeholder."""
    import pytest

    pytest.importorskip("fastapi")
    from fastapi import FastAPI

    from src.maintenance.api import register

    app = FastAPI()
    register(app)
    paths = {getattr(r, "path", None) for r in app.router.routes}
    assert "/api/maintenance/metrics" in paths
    assert "/api/maintenance/tasks" in paths


def test_genome_stats_degrades_when_getter_raises(monkeypatch) -> None:
    import src.novamind.genome_v2 as gv2
    import src.maintenance.api as api

    def boom():
        raise RuntimeError("no genome")

    monkeypatch.setattr(gv2, "get_genome_v2", boom)
    # _genome_stats() must swallow the failure and return an empty mapping
    assert api._genome_stats() == {}
    # ...and the public snapshot still answers with zeros
    payload = api.metrics_snapshot()
    assert payload["ok"] is True and payload["genome"]["agents"] == 0


def test_genome_document_degrades_when_getter_raises(monkeypatch) -> None:
    import src.novamind.genome_v2 as gv2
    import src.maintenance.api as api

    def boom():
        raise RuntimeError("no genome")

    monkeypatch.setattr(gv2, "get_genome_v2", boom)
    assert api._genome_document() == {}


def test_tasks_route_degrades_on_bad_limit(monkeypatch) -> None:
    """A broken task generator yields an honest error payload, never a 500."""
    import src.maintenance.api as api

    def boom(_genome, *, limit):
        raise RuntimeError("generator exploded")

    monkeypatch.setattr(api, "generate_tasks", boom)
    client, _child, _FastAPI, _build = _api_client()
    resp = client.get("/api/maintenance/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["tasks"] == []
    assert "generator exploded" in body["error"]
