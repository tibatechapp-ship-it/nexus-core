"""Tests for the Agent Genome (v2.2).

The genome core is pure Python (scoring) plus a stdlib SQLite store, so these
run in the phone framework gate with no ``novamind`` extras and no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.novamind.core.session_store import SessionStore
from src.novamind.genome import (
    DEFAULT_PERSONAS,
    NEUTRAL_STANDING,
    Genome,
    classify,
    compute_standing,
)
from src.novamind.genome.scoring import (
    avg_latency,
    consensus_avg,
    speed_score,
    success_rate,
)


@pytest.fixture()
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.db")


@pytest.fixture()
def genome(store: SessionStore) -> Genome:
    g = Genome(store)
    g.seed()
    return g


# ── pure scoring ─────────────────────────────────────────────────────────────
def test_success_rate_zero_runs_is_zero() -> None:
    assert success_rate(0, 0) == 0.0


def test_success_rate_half() -> None:
    assert success_rate(2, 4) == 0.5


def test_success_rate_clamped() -> None:
    assert success_rate(10, 4) == 1.0


def test_avg_latency() -> None:
    assert avg_latency(3000, 3) == 1000.0


def test_avg_latency_no_runs() -> None:
    assert avg_latency(0, 0) == 0.0


def test_consensus_avg_no_samples_is_neutral() -> None:
    assert consensus_avg(0.0, 0) == 0.5


def test_consensus_avg_value() -> None:
    assert consensus_avg(1.5, 3) == 0.5


def test_speed_score_instant_is_one() -> None:
    assert speed_score(0.0) == 1.0


def test_speed_score_at_ceiling_is_zero() -> None:
    assert speed_score(30_000.0) == 0.0


def test_speed_score_over_ceiling_clamped() -> None:
    assert speed_score(90_000.0) == 0.0


def test_compute_standing_no_runs_keeps_prior() -> None:
    assert compute_standing(0, 0, 0, 0, 0) == NEUTRAL_STANDING


def test_compute_standing_perfect_is_one() -> None:
    assert compute_standing(5, 5, 5.0, 5, 0) == 1.0


def test_compute_standing_poor_is_low() -> None:
    assert compute_standing(4, 0, 0.0, 4, 120_000) == 0.0


def test_classify_buckets() -> None:
    assert classify(0.9) == "promoted"
    assert classify(0.5) == "active"
    assert classify(0.1) == "probation"


# ── store level ──────────────────────────────────────────────────────────────
def test_upsert_agent_is_idempotent(store: SessionStore) -> None:
    a = store.upsert_agent("analyst", name="المُحلِّل", persona="p")
    b = store.upsert_agent("analyst", name="other", persona="q")
    assert a["agent_id"] == b["agent_id"]
    assert b["name"] == "المُحلِّل"  # second call does not overwrite
    assert store.get_agent("missing") is None


def test_record_agent_outcome_increments(store: SessionStore) -> None:
    store.upsert_agent("analyst")
    row = store.record_agent_outcome("analyst", success=True, latency_ms=1000,
                                     consensus=0.8, standing=0.7, status="promoted")
    assert row["runs"] == 1
    assert row["successes"] == 1
    assert row["failures"] == 0
    assert row["latency_sum_ms"] == 1000
    assert row["consensus_n"] == 1
    assert row["standing"] == 0.7
    assert row["status"] == "promoted"


def test_record_agent_outcome_autocreates(store: SessionStore) -> None:
    row = store.record_agent_outcome("ghost", success=False)
    assert row["agent_id"] == "ghost"
    assert row["failures"] == 1


def test_record_without_consensus_does_not_count(store: SessionStore) -> None:
    store.upsert_agent("analyst")
    row = store.record_agent_outcome("analyst", success=True)
    assert row["consensus_n"] == 0
    assert row["consensus_sum"] == 0.0


def test_list_agents_ranked_by_standing(store: SessionStore) -> None:
    store.upsert_agent("low")
    store.upsert_agent("high")
    store.record_agent_outcome("low", success=True, standing=0.2, status="probation")
    store.record_agent_outcome("high", success=True, standing=0.9, status="promoted")
    assert [a["agent_id"] for a in store.list_agents()] == ["high", "low"]


def test_update_agent_persona(store: SessionStore) -> None:
    store.upsert_agent("analyst", persona="old")
    assert store.update_agent("analyst", persona="new")
    assert store.get_agent("analyst")["persona"] == "new"
    assert store.update_agent("analyst") is False
    assert store.update_agent("ghost", persona="x") is False


def test_agent_timeline_records_events(store: SessionStore) -> None:
    store.upsert_agent("analyst")
    store.record_agent_outcome("analyst", success=True)
    kinds = [e["kind"] for e in store.agent_timeline("analyst")]
    assert "born" in kinds and "outcome" in kinds


def test_reset_agent_bumps_generation_and_zeroes(store: SessionStore) -> None:
    store.upsert_agent("analyst")
    store.record_agent_outcome("analyst", success=True, standing=0.9, status="promoted")
    row = store.reset_agent("analyst")
    assert row is not None
    assert row["runs"] == 0
    assert row["standing"] == NEUTRAL_STANDING
    assert row["status"] == "active"
    assert row["generation"] == 2
    assert store.reset_agent("ghost") is None


def test_stats_includes_agents(store: SessionStore) -> None:
    store.upsert_agent("analyst")
    assert store.stats()["agents"] == 1


# ── manager level ────────────────────────────────────────────────────────────
def test_seed_creates_all_roles(genome: Genome) -> None:
    ids = {a["agent_id"] for a in genome.rank()}
    assert set(DEFAULT_PERSONAS).issubset(ids)


def test_seed_is_idempotent(genome: Genome) -> None:
    assert genome.seed() == 0


def test_record_promotes_a_strong_agent(genome: Genome) -> None:
    for _ in range(4):
        genome.record("analyst", success=True, latency_ms=500, consensus=0.9)
    row = genome.detail("analyst")
    assert row is not None
    assert row["status"] == "promoted"
    assert row["standing"] >= 0.7


def test_record_puts_a_weak_agent_on_probation(genome: Genome) -> None:
    for _ in range(4):
        genome.record("critic", success=False, latency_ms=40_000, consensus=0.0)
    row = genome.detail("critic")
    assert row is not None
    assert row["status"] == "probation"


def test_outcome_from_influence_win(genome: Genome) -> None:
    row = genome.outcome_from_influence("expert", alignment=0.9, standing_delta=1,
                                        consensus=0.8)
    assert row["successes"] == 1
    assert row["consensus_n"] == 1


def test_outcome_from_influence_loss(genome: Genome) -> None:
    row = genome.outcome_from_influence("expert", alignment=0.1, standing_delta=-1,
                                        consensus=0.3)
    assert row["failures"] == 1


def test_detail_missing_returns_none(genome: Genome) -> None:
    assert genome.detail("nope") is None


def test_export_contains_agents_and_events(genome: Genome) -> None:
    genome.record("analyst", success=True)
    payload = genome.export()
    assert payload["version"] == 1
    assert any(a["agent_id"] == "analyst" for a in payload["agents"])
    assert "analyst" in payload["events"]


def test_import_is_idempotent(genome: Genome) -> None:
    payload = genome.export()
    assert genome.import_(payload) == 0  # everything already present


def test_import_adds_new_agent(genome: Genome) -> None:
    n = genome.import_({"agents": [{"agent_id": "newbie", "name": "جديد",
                                    "persona": "p", "standing": 0.6}]})
    assert n == 1
    got = genome.detail("newbie")
    assert got is not None and got["standing"] == 0.6


def test_reset_keeps_agent_and_lineage(genome: Genome) -> None:
    genome.record("analyst", success=True, latency_ms=100, consensus=0.9)
    row = genome.reset("analyst")
    assert row is not None
    assert row["generation"] == 2
    assert genome.detail("analyst")["timeline"][0]["kind"] == "reset"


# ── council ↔ genome integration ─────────────────────────────────────────────
def test_council_debate_feeds_the_genome(genome: Genome, store: SessionStore) -> None:
    from src.novamind.council import Council

    council = Council(router=None, store=store, genome=genome)  # offline, fast
    council.debate("هل نطلق v2.0؟", rounds=1)
    rows = genome.rank()
    assert any(a["runs"] > 0 for a in rows)
    analyst = genome.detail("analyst")
    assert analyst is not None
    kinds = [e["kind"] for e in analyst["timeline"]]
    assert "council" in kinds


def test_council_without_genome_still_works(store: SessionStore) -> None:
    from src.novamind.council import Council

    council = Council(router=None, store=store)  # no genome wired
    result = council.debate("topic", rounds=1)
    assert result["consensus"] >= 0.0
    assert store.stats()["council_sessions"] == 1

