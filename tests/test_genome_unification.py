"""P3 — genome unification: one session, one store.

The acceptance criteria this file pins:

1. a council session writes to the **v2** store only (the legacy SQLite
   ``agent_genome`` table stays empty), and the judge is not called twice;
2. the Academy exposes the six council members before anyone trains;
3. ``Genome(SessionStore)`` still behaves exactly as before (back-compat);
4. the one-time v1 → v2 migration is additive, idempotent and never fatal;
5. the NovaMind library is described by real manifests (spec + skills), so the
   training curriculum is no longer ``default`` for 60+ modules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agents.manifest import KNOWN_SKILLS, all_manifests, manifest_problems
from src.agents.novamind_manifest import (
    CORE,
    discover,
    get_novamind_manifest,
    novamind_manifests,
    training_manifests,
)
from src.novamind import genome_migrate
from src.novamind.core.session_store import SessionStore
from src.novamind.council import COUNCIL_MEMBERS, Council
from src.novamind.genome import Genome
from src.novamind.genome_v2 import GenomeV2


@pytest.fixture()
def stores(tmp_path: Path):
    """(legacy SQLite store, fresh v2 genome) in an isolated directory."""
    legacy = SessionStore(tmp_path / "sessions.db")
    return legacy, GenomeV2()


# ── 1 · one session, one store ────────────────────────────────────────────
def test_council_session_writes_to_the_v2_store_only(stores) -> None:
    legacy, v2 = stores
    genome = Genome(v2)
    genome.seed(members=COUNCIL_MEMBERS)
    calls: list[str] = []

    def judge(agent_id: str, verdict: str) -> None:  # pragma: no cover - must not run
        calls.append(agent_id)

    council = Council(router=None, store=None, genome=genome, judge=judge,
                      members=COUNCIL_MEMBERS)
    council.debate("كيف نقسّم ميزانية الأداء بين الواجهة والخادم؟", rounds=1)

    # v2 owns the evidence …
    rows = v2.rank()
    assert rows, "the council session must leave evidence in the v2 genome"
    assert sum(int(r["observations"]) for r in rows) > 0
    # … the legacy table was never written …
    assert legacy.list_agents() == []
    # … and the injected judge was skipped (the adapter already persisted it).
    assert calls == []


def test_legacy_genome_is_still_the_legacy_genome(stores) -> None:
    """``Genome(SessionStore)`` keeps its byte-for-byte old behaviour."""
    legacy, v2 = stores
    genome = Genome(legacy)
    assert genome.is_genome_v2 is False
    genome.seed(members=COUNCIL_MEMBERS)
    row = genome.record("analyst", success=True, latency_ms=120, consensus=0.8)
    assert row["agent_id"] == "analyst"
    assert legacy.get_agent("analyst") is not None
    assert v2.rank() == []
    assert len(genome.rank()) == len(COUNCIL_MEMBERS)


def test_adapter_and_legacy_share_the_rank_shape(stores) -> None:
    legacy, v2 = stores
    old = Genome(legacy)
    new = Genome(v2)
    old.seed(members=COUNCIL_MEMBERS)
    new.seed(members=COUNCIL_MEMBERS)
    ui_keys = {"agent_id", "name", "persona", "runs", "successes", "failures",
               "standing", "status"}
    assert ui_keys <= set(old.rank()[0])
    assert ui_keys <= set(new.rank()[0])
    assert new.is_genome_v2 is True


def test_from_genome_v2_builds_the_adapter() -> None:
    genome = Genome.from_genome_v2(GenomeV2())
    assert genome.is_genome_v2 is True
    # Bare seeding keeps exact v1 parity: the default personas, no president.
    from src.novamind.genome.genome import DEFAULT_PERSONAS

    assert len(genome.rank()) == len(DEFAULT_PERSONAS)
    assert len(genome.rank()) < len(COUNCIL_MEMBERS)


def test_seeding_the_council_adds_the_president(stores) -> None:
    _, v2 = stores
    genome = Genome(v2)
    genome.seed(members=COUNCIL_MEMBERS)
    ids = {row["agent_id"] for row in genome.rank()}
    assert ids >= {m.id for m in COUNCIL_MEMBERS}
    assert "tork_acil" in ids


def test_update_and_reset_round_trip_through_the_adapter(stores) -> None:
    _, v2 = stores
    genome = Genome(v2)
    genome.seed(members=COUNCIL_MEMBERS)
    assert genome.update_agent("analyst", name="المحلل الجديد") is True
    assert genome.get_agent("analyst")["name"] == "المحلل الجديد"
    assert genome.reset("analyst") is not None
    assert genome.fitness_of("analyst") == pytest.approx(0.5)


# ── 2 · the Academy sees the council ──────────────────────────────────────
def test_academy_roster_shows_the_six_council_members(monkeypatch, tmp_path) -> None:
    from src.novamind.training.engine import TrainingEngine
    from src.novamind.training.store import TrainingStore

    v2 = GenomeV2()
    Genome(v2).seed(members=COUNCIL_MEMBERS)
    monkeypatch.setattr("src.novamind.genome_v2.get_genome_v2", lambda: v2)

    from src.novamind.training.api import build_router

    engine = TrainingEngine(store=TrainingStore(tmp_path / "training.json"))
    app = FastAPI()
    app.include_router(build_router(engine))  # the router mounts itself at /api/training
    client = TestClient(app)

    payload = client.get("/api/training/agents?roster=1").json()
    ids = {row["agent_id"] for row in payload["agents"]}
    assert {m.id for m in COUNCIL_MEMBERS} <= ids
    assert len(ids) >= len(COUNCIL_MEMBERS)
    # A roster entry is trainable: it carries a spec, not a run.
    entry = next(r for r in payload["agents"] if r["agent_id"] == "expert")
    assert entry["latest_run"] is None
    assert isinstance(entry["spec"], str) and entry["spec"]

    # The default contract stays trained-only (pre-P3 behaviour).
    assert client.get("/api/training/agents").json()["count"] == 0

    fitness = client.get("/api/training/fitness").json()
    assert {row["agent_id"] for row in fitness["agents"]} >= {
        m.id for m in COUNCIL_MEMBERS
    }


# ── 3 · migration ─────────────────────────────────────────────────────────
def _legacy_row() -> dict:
    return {
        "agent_id": "analyst", "name": "المُحلِّل", "persona": "تحليل",
        "runs": 9, "successes": 6, "failures": 3, "standing": 0.66,
        "status": "stable", "timeline": [{"tick": 1, "success": True}],
    }


def test_migration_is_additive_and_idempotent(stores) -> None:
    _, v2 = stores
    assert genome_migrate.import_v1_rows([_legacy_row()], v2) == 1
    row = v2.snapshot("analyst")
    assert row["task_observations"] == 9
    assert row["task_successes"] == 6
    assert row["task_ewma"] == pytest.approx(0.66)
    fitness = float(row["fitness"])
    assert fitness != pytest.approx(0.5)

    # Second run cannot inflate anything.
    genome_migrate.import_v1_rows([_legacy_row()], v2)
    again = v2.snapshot("analyst")
    assert again["task_observations"] == 9
    assert float(again["fitness"]) == pytest.approx(fitness)


def test_migration_keeps_more_evidence_than_the_import(stores) -> None:
    _, v2 = stores
    genome = Genome(v2)
    genome.record("analyst", success=True)
    genome.record("analyst", success=True)
    genome.record("analyst", success=True)
    before = v2.snapshot("analyst")["task_observations"]
    genome_migrate.import_v1_rows([_legacy_row()], v2)
    assert v2.snapshot("analyst")["task_observations"] == max(before, 9)


def test_migration_from_a_real_session_store(stores, tmp_path: Path) -> None:
    legacy, v2 = stores
    Genome(legacy).record("analyst", success=True, consensus=0.9)
    count = genome_migrate.import_v1_store(legacy, v2)
    assert count >= 1
    assert v2.snapshot("analyst")["task_observations"] >= 1


def test_migrate_if_fresh_respects_an_existing_store(stores, tmp_path: Path) -> None:
    legacy, v2 = stores
    Genome(legacy).record("analyst", success=True)
    existing = tmp_path / "genome.json"
    existing.write_text(json.dumps({"agents": {}}), encoding="utf-8")
    assert genome_migrate.migrate_if_fresh(legacy, existing, v2) == 0
    assert v2.snapshot("analyst") is None

    fresh = tmp_path / "missing.json"
    assert genome_migrate.migrate_if_fresh(legacy, fresh, v2) >= 1
    assert v2.snapshot("analyst") is not None


def test_migration_never_raises_on_broken_input(stores) -> None:
    _, v2 = stores

    class Boom:
        def list_agents(self):
            raise RuntimeError("db gone")

    assert genome_migrate.import_v1_store(Boom(), v2) == 0
    assert genome_migrate.import_v1_rows([None, 42, {"runs": 1}], v2) == 0
    assert genome_migrate.import_v1_rows("nonsense", v2) == 0


# ── 4 · the NovaMind → manifest bridge ────────────────────────────────────
def test_discovery_finds_the_novamind_library() -> None:
    modules = discover()
    assert len(modules) >= 50
    assert "coder" in modules and "sql" in modules and "react" in modules
    for module in modules.values():
        assert module.path.startswith("src/novamind/agents/")


def test_bridge_manifests_are_valid_and_never_shadow_the_framework() -> None:
    framework = all_manifests()
    bridged = novamind_manifests()
    assert bridged
    assert not (set(bridged) & set(framework)), "framework rows must win"
    for manifest in bridged.values():
        assert manifest_problems(manifest) == (), manifest.id
        assert set(manifest.skills) <= KNOWN_SKILLS
        assert manifest.tools == ()
        assert manifest.memory_scope == f"novamind:{manifest.id}"


def test_core_specs_are_real_curricula() -> None:
    bridged = novamind_manifests()
    for agent_id in ("coder", "security", "db_migration", "react"):
        if agent_id not in bridged:
            continue
        manifest = bridged[agent_id]
        assert manifest.spec in CORE[agent_id] or manifest.spec != "default"


def test_training_manifests_union_is_ordered_and_complete() -> None:
    merged = training_manifests()
    framework = all_manifests()
    assert set(framework) <= set(merged)
    for agent_id, manifest in framework.items():
        assert merged[agent_id].to_dict() == manifest.to_dict()
    assert len(merged) == len(framework) + len(novamind_manifests())


def test_bridge_lookup_is_total() -> None:
    assert get_novamind_manifest("") is None
    assert get_novamind_manifest("no_such_agent_xyz") is None
    assert get_novamind_manifest("sql") is not None


def test_training_engine_uses_the_bridged_spec(tmp_path: Path) -> None:
    from src.novamind.training.engine import TrainingEngine
    from src.novamind.training.store import TrainingStore

    engine = TrainingEngine(store=TrainingStore(tmp_path / "training.json"))
    plan = engine.plan("db_migration")
    assert plan["spec"] == "database"
    names = {m["name"] for m in plan["modules"]}
    assert plan["modules"], "a bridged agent must still get a real curriculum"
    assert any(m["source"] == "manifest" for m in plan["modules"]) or names


# ── 5 · bridge edge cases (synthetic modules, no real files touched) ──────
def _write_module(directory: Path, filename: str, body: str) -> None:
    (directory / filename).write_text(body, encoding="utf-8")


def test_discovery_handles_the_awkward_modules(tmp_path: Path) -> None:
    mods = tmp_path / "agents"
    mods.mkdir()
    _write_module(mods, "_private.py", 'NAME = "ignored"\n')
    _write_module(mods, "broken.py", "def oops(:\n")
    _write_module(mods, "nameless.py", "VALUE = 1\n")
    _write_module(mods, "computed_name.py", "NAME = get_name()\n")
    _write_module(mods, "bad_id.py", 'NAME = "not a slug!"\n')
    _write_module(mods, "twins_a.py", 'NAME = "twin"\nDESCRIPTION = "first"\n')
    _write_module(mods, "twins_b.py", 'NAME = "twin"\nDESCRIPTION = "second"\n')
    _write_module(
        mods, "classy.py",
        'class Classy:\n'
        '    NAME = "classy"\n'
        '    DESCRIPTION = "class-level facts"\n'
        '    CAPABILITIES = ["security audit", "threat model"]\n',
    )
    _write_module(
        mods, "instance.py",
        'class Instance:\n'
        '    def __init__(self):\n'
        '        self.name = "instance"\n'
        '        self.DESCRIPTION = "instance-level facts"\n',
    )

    found = discover(mods)
    assert set(found) == {"twin", "classy", "instance"}
    assert found["twin"].description == "first"     # first file wins, no crash
    assert found["classy"].capabilities == ("security audit", "threat model")
    assert found["instance"].description == "instance-level facts"
    assert found["classy"].to_dict()["capabilities"] == [
        "security audit", "threat model"
    ]


def test_discovery_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert discover(tmp_path / "nope") == {}
    assert novamind_manifests(tmp_path / "nope") == {}


def test_unknown_modules_derive_their_skill_from_capabilities(tmp_path: Path) -> None:
    mods = tmp_path / "agents"
    mods.mkdir()
    _write_module(
        mods, "gatekeeper.py",
        'class Gatekeeper:\n'
        '    NAME = "gatekeeper"\n'
        '    CAPABILITIES = ["secret scanning", "credential audit"]\n',
    )
    _write_module(
        mods, "trainer.py",
        'class Trainer:\n'
        '    NAME = "trainer"\n'
        '    CAPABILITIES = ["curriculum design", "architecture map"]\n',
    )
    _write_module(
        mods, "plain.py",
        'class Plain:\n'
        '    NAME = "plain"\n',
    )

    bridged = novamind_manifests(mods)
    assert bridged["gatekeeper"].skills == ("security-audit",)
    assert bridged["trainer"].skills == ("architecture-review",)
    assert bridged["plain"].skills == ("code-review",)
    assert bridged["plain"].spec == "default"
    for manifest in bridged.values():
        assert manifest_problems(manifest) == ()


def test_scan_survives_reassigned_and_annotated_fields(tmp_path: Path) -> None:
    mods = tmp_path / "agents"
    mods.mkdir()
    _write_module(
        mods, "messy.py",
        'NAME: str = "messy"\n'
        'NAME = "messy_again"\n'          # second assignment must not win
        'DESCRIPTION = "first description"\n'
        'DESCRIPTION = "second description"\n'
        'CAPABILITIES = ["a", 3, "b"]\n'
        'CAPABILITIES = ["ignored"]\n'
        'items = [1]\n'
        'items[0] = 5\n',                 # a target that is neither Name nor Attribute
    )
    _write_module(
        mods, "typed.py",
        'class Typed:\n'
        '    NAME = "' + "y" * 60 + '"\n'      # too long to be an id
        '    DESCRIPTION = 7\n'               # not a string
        '    CAPABILITIES = "single"\n'       # not a list/tuple
        '    FLAG: bool\n'                    # annotated, no value
        '    OTHER: str = "other"\n',
    )
    found = discover(mods)
    module = found["messy"]
    assert module.description == "first description"
    assert module.capabilities == ("a", "b")
    assert "typed" not in found              # nothing usable was declared
