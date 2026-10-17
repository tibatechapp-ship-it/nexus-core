"""Tests for the Agent Genome v2 (v1.14.0).

The genome is pure standard library — no ``novamind`` extras, no network, no
disk, no clock — so the whole model (including the council-engine wiring) is
exercised hermetically in the phone framework gate and on CI.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from src.council.engine import CouncilEngine
from src.novamind.genome_v2 import (
    CONFIDENCE_K,
    ELITE_AT,
    FINAL_VERDICTS,
    HISTORY_LIMIT,
    MIN_OBSERVATIONS,
    NEUTRAL_FITNESS,
    PROBATION_BELOW,
    GenomeV2,
    agreement,
    classify_fitness,
    confidence,
    empty_genome,
    ewma_update,
    fitness,
    get_genome_v2,
    reset_genome_v2,
    stance_of,
    trait_accuracy,
)

_STANCE_WORD = {"yes": "موافق", "no": "مرفوض", "mid": "محايد"}


def _entry(member: str, stance: str) -> dict[str, Any]:
    """A transcript row whose explicit verdict is ``stance``."""
    return {"member": member, "response": f"تحليل … [الحكم: {_STANCE_WORD[stance]}]"}


# ══ pure helpers ═════════════════════════════════════════════════════════════
@pytest.mark.parametrize("value,expected", [
    ("yes", "approve"), ("approve", "approve"), ("APPROVE", "approve"),
    ("no", "reject"), ("reject", "reject"),
    ("mid", "human_review"), ("human_review", "human_review"),
    ("  Mid  ", "human_review"),
])
def test_stance_of_normalises(value: str, expected: str) -> None:
    assert stance_of(value) == expected


@pytest.mark.parametrize("value", [None, "", "banana", 42, "unknown"])
def test_stance_of_unknown_is_none(value: Any) -> None:
    assert stance_of(value) is None


@pytest.mark.parametrize("member,final,expected", [
    ("yes", "approve", True),
    ("no", "approve", False),
    ("mid", "human_review", True),
    ("yes", "human_review", False),
    ("no", "reject", True),
])
def test_agreement_pairs(member: str, final: str, expected: bool) -> None:
    assert agreement(member, final) is expected


def test_agreement_unscorable_is_none() -> None:
    assert agreement("banana", "approve") is None
    assert agreement("yes", "banana") is None
    assert agreement(None, None) is None


def test_confidence_zero_without_observations() -> None:
    assert confidence(0) == 0.0
    assert confidence(-5) == 0.0


def test_confidence_monotone_and_bounded() -> None:
    assert 0.0 < confidence(1) < confidence(5) < confidence(50) < 1.0


def test_confidence_with_zero_k_is_certain() -> None:
    assert confidence(1, k=0.0) == 1.0
    assert confidence(0, k=0.0) == 0.0


def test_confidence_known_value() -> None:
    assert confidence(int(CONFIDENCE_K), CONFIDENCE_K) == 0.5


def test_ewma_first_blend_is_between() -> None:
    assert ewma_update(0.0, 1.0) == pytest.approx(0.35, abs=1e-6)


def test_ewma_alpha_clamped() -> None:
    assert ewma_update(0.0, 1.0, alpha=5.0) == 1.0
    assert ewma_update(1.0, 0.0, alpha=-1.0) == 1.0


def test_ewma_stays_in_unit_range() -> None:
    assert 0.0 <= ewma_update(NEUTRAL_FITNESS, 1.0) <= 1.0


def test_fitness_neutral_without_evidence() -> None:
    assert fitness(0, 1.0) == NEUTRAL_FITNESS


def test_fitness_shrinks_toward_neutral() -> None:
    # One perfect sample is not enough to look elite.
    assert fitness(1, 1.0) < ELITE_AT
    assert NEUTRAL_FITNESS < fitness(1, 1.0)


def test_fitness_converges_on_ewma_with_evidence() -> None:
    # Confidence never reaches exactly 1, so fitness approaches the EWMA.
    assert fitness(500, 1.0) == pytest.approx(1.0, abs=0.01)
    assert fitness(500, 0.0) == pytest.approx(0.0, abs=0.01)


def test_fitness_honours_custom_prior() -> None:
    assert fitness(0, 0.0, prior=0.9) == 0.9


@pytest.mark.parametrize("value,expected", [
    (0.0, "probationary"), (0.34, "probationary"),
    (0.35, "stable"), (0.5, "stable"), (0.74, "stable"),
    (0.75, "elite"), (1.0, "elite"),
])
def test_classify_fitness_bands(value: float, expected: str) -> None:
    assert classify_fitness(value) == expected


def test_trait_accuracy_none_for_unseen() -> None:
    traits = empty_genome("x")["traits"]
    assert trait_accuracy(traits, "approve") is None
    assert trait_accuracy(traits, "banana") is None
    assert trait_accuracy({}, "approve") is None


def test_trait_accuracy_value() -> None:
    traits = {"reject": {"observations": 4, "agreements": 3}}
    assert trait_accuracy(traits, "no") == 0.75
    assert trait_accuracy(traits, "reject") == 0.75


def test_empty_genome_shape() -> None:
    row = empty_genome("critic", generation=3, parent="critic")
    assert row["agent_id"] == "critic"
    assert row["generation"] == 3 and row["parent"] == "critic"
    assert row["fitness"] == NEUTRAL_FITNESS and row["status"] == "stable"
    assert row["retired"] is False and row["history"] == []
    assert set(row["traits"]) == set(FINAL_VERDICTS)


# ══ GenomeV2 ═════════════════════════════════════════════════════════════════
def test_ensure_is_idempotent() -> None:
    genome = GenomeV2()
    assert genome.ensure("analyst") is genome.ensure("analyst")


def test_observe_counts_agreement() -> None:
    genome = GenomeV2()
    row = genome.observe("analyst", "yes", "approve")
    assert row["observations"] == 1 and row["agreements"] == 1
    assert row["dissent"] == 0 and row["streak"] == 1 and row["best_streak"] == 1
    assert row["ewma"] == 1.0 and row["traits"]["approve"]["agreements"] == 1


def test_observe_counts_dissent_and_resets_streak() -> None:
    genome = GenomeV2()
    genome.observe("analyst", "yes", "approve")
    row = genome.observe("analyst", "no", "approve")
    assert row["observations"] == 2 and row["agreements"] == 1
    assert row["dissent"] == 1 and row["streak"] == 0 and row["best_streak"] == 1


def test_observe_unscorable_is_not_counted() -> None:
    genome = GenomeV2()
    row = genome.observe("analyst", "banana", "approve")
    assert row["unscored"] == 1 and row["observations"] == 0
    assert row["fitness"] == NEUTRAL_FITNESS
    assert row["history"][-1]["event"] == "unscored"


def test_observe_history_records_stance_and_final() -> None:
    genome = GenomeV2()
    genome.observe("critic", "no", "reject")
    event = genome.snapshot("critic")["history"][-1]  # type: ignore[index]
    assert event == {"seq": 1, "event": "agreement",
                     "stance": "no", "final": "reject"}


def test_history_is_bounded() -> None:
    genome = GenomeV2()
    for _ in range(HISTORY_LIMIT + 10):
        genome.observe("analyst", "yes", "approve")
    assert len(genome.snapshot("analyst")["history"]) == HISTORY_LIMIT  # type: ignore[index]


def test_perfect_agent_becomes_elite() -> None:
    genome = GenomeV2()
    for _ in range(12):
        row = genome.observe("analyst", "yes", "approve")
    assert row["status"] == "elite" and row["fitness"] >= ELITE_AT


def test_wrong_agent_becomes_probationary() -> None:
    genome = GenomeV2()
    for _ in range(12):
        row = genome.observe("critic", "yes", "reject")
    assert row["status"] == "probationary" and row["fitness"] < PROBATION_BELOW


def test_traits_split_by_final_verdict() -> None:
    genome = GenomeV2()
    genome.observe("analyst", "yes", "approve")   # agree
    genome.observe("analyst", "yes", "reject")    # dissent
    traits = genome.snapshot("analyst")["traits"]  # type: ignore[index]
    assert trait_accuracy(traits, "approve") == 1.0
    assert trait_accuracy(traits, "reject") == 0.0
    assert trait_accuracy(traits, "human_review") is None


def test_observe_council_records_every_member() -> None:
    genome = GenomeV2()
    rows = genome.observe_council(
        {"profiler": "yes", "analyst": "mid", "critic": "no"}, "approve")
    assert len(rows) == 3
    assert genome.snapshot("profiler")["agreements"] == 1  # type: ignore[index]
    assert genome.snapshot("analyst")["last_final"] == "approve"  # type: ignore[index]
    assert genome.snapshot("critic")["dissent"] == 1  # type: ignore[index]


def test_observe_council_tolerates_empty_and_none() -> None:
    genome = GenomeV2()
    assert genome.observe_council({}, "approve") == []
    assert genome.observe_council(None, "approve") == []  # type: ignore[arg-type]


def test_rank_orders_by_fitness() -> None:
    genome = GenomeV2()
    for _ in range(12):
        genome.observe("analyst", "yes", "approve")
        genome.observe("critic", "yes", "reject")
    assert [r["agent_id"] for r in genome.rank()] == ["analyst", "critic"]
    assert genome.leaders(1)[0]["agent_id"] == "analyst"


def test_rank_ties_prefer_more_evidence() -> None:
    genome = GenomeV2()
    genome.observe("critic", "yes", "approve")
    for _ in range(6):
        genome.observe("analyst", "yes", "approve")
    assert [r["agent_id"] for r in genome.rank()] == ["analyst", "critic"]


def test_rank_limit_and_empty() -> None:
    assert GenomeV2().rank() == []
    genome = GenomeV2()
    genome.observe("analyst", "yes", "approve")
    assert genome.rank(limit=0) == []
    assert len(genome.leaders(5)) == 1


def test_retire_hides_from_rank_and_revive_restores() -> None:
    genome = GenomeV2()
    genome.observe("critic", "yes", "approve")
    genome.retire("critic", note="noisy")
    assert genome.rank() == []
    assert len(genome.rank(include_retired=True)) == 1
    assert genome.snapshot("critic")["retired"] is True  # type: ignore[index]
    genome.revive("critic")
    assert len(genome.rank()) == 1


def test_probationary_filters_status() -> None:
    genome = GenomeV2()
    for _ in range(12):
        genome.observe("critic", "yes", "reject")
        genome.observe("analyst", "yes", "approve")
    assert [r["agent_id"] for r in genome.probationary()] == ["critic"]


def test_mutate_resets_and_bumps_generation() -> None:
    genome = GenomeV2()
    for _ in range(6):
        genome.observe("critic", "yes", "reject")
    fresh = genome.mutate("critic", note="retrain")
    assert fresh["generation"] == 2 and fresh["parent"] == "critic"
    assert fresh["observations"] == 0 and fresh["fitness"] == NEUTRAL_FITNESS
    assert fresh["history"] == [{"seq": 7, "event": "mutation",
                                 "note": "retrain", "from_generation": 1}]


@pytest.mark.parametrize("observations,final,expected", [
    (0, "approve", "unknown"),
    (MIN_OBSERVATIONS - 1, "approve", "observe"),
    (12, "approve", "promote"),
    (12, "reject", "retrain"),
])
def test_advise_actions(observations: int, final: str, expected: str) -> None:
    genome = GenomeV2()
    for _ in range(observations):
        genome.observe("analyst", "yes", final)
    assert genome.advise("analyst")["action"] == expected


def test_advise_observe_for_a_known_but_unobserved_agent() -> None:
    genome = GenomeV2()
    genome.ensure("analyst")
    advice = genome.advise("analyst")
    assert advice["action"] == "observe" and advice["observations"] == 0


def test_advise_keep_in_stable_band() -> None:
    genome = GenomeV2()
    for _ in range(8):
        genome.observe("analyst", "yes", "approve")
        genome.observe("analyst", "no", "approve")
    assert genome.advise("analyst")["action"] == "keep"


def test_advise_unknown_and_retired() -> None:
    genome = GenomeV2()
    assert genome.advise("ghost")["action"] == "unknown"
    genome.observe("critic", "yes", "approve")
    genome.retire("critic")
    assert genome.advise("critic")["action"] == "revise"


def test_stats_aggregates() -> None:
    genome = GenomeV2()
    for _ in range(12):
        genome.observe("analyst", "yes", "approve")
        genome.observe("critic", "yes", "reject")
    genome.retire("critic")
    stats = genome.stats()
    assert stats["agents"] == 2 and stats["active"] == 1 and stats["retired"] == 1
    assert stats["elite"] == 1 and stats["observations"] == 24
    assert stats["mean_fitness"] >= ELITE_AT


def test_stats_empty_is_neutral() -> None:
    stats = GenomeV2().stats()
    assert stats["agents"] == 0 and stats["mean_fitness"] == NEUTRAL_FITNESS


def test_to_dict_round_trip() -> None:
    genome = GenomeV2(alpha=0.5)
    for _ in range(6):
        genome.observe("analyst", "yes", "approve")
    genome.retire("critic")
    payload = genome.to_dict()
    assert payload["version"] == 2 and payload["alpha"] == 0.5

    restored = GenomeV2.from_dict(payload)
    assert restored.stats() == genome.stats()
    assert restored.snapshot("analyst") == genome.snapshot("analyst")
    assert restored.snapshot("critic")["retired"] is True  # type: ignore[index]


def test_from_dict_tolerates_junk() -> None:
    assert GenomeV2.from_dict(None).stats()["agents"] == 0
    assert GenomeV2.from_dict({}).stats()["agents"] == 0
    restored = GenomeV2.from_dict({"agents": {"x": "not-a-mapping", "y": {}}})
    assert restored.stats()["agents"] == 1
    assert restored.snapshot("y")["observations"] == 0  # type: ignore[index]
    partial = GenomeV2.from_dict({"agents": {"z": {"traits": {"reject": {"agreements": 2}}}}})
    assert partial.snapshot("z")["traits"]["reject"] == {"observations": 0, "agreements": 2}  # type: ignore[index]


def test_snapshot_unknown_is_none() -> None:
    assert GenomeV2().snapshot("ghost") is None


def test_shared_singleton_is_reused_and_resettable() -> None:
    first = get_genome_v2()
    assert get_genome_v2() is first
    first.observe("analyst", "yes", "approve")
    fresh = reset_genome_v2()
    assert fresh is not first
    assert fresh.stats()["agents"] == 0
    assert get_genome_v2() is fresh


# ══ council-engine wiring (v1.14.0) ═════════════════════════════════════════
def _engine(genome: Any = None) -> CouncilEngine:
    return CouncilEngine(llm_router=None, genome=genome)


def _consensus_transcript() -> list[dict[str, Any]]:
    return [_entry("profiler", "yes"), _entry("analyst", "yes"), _entry("critic", "no")]


def test_judge_verdict_is_unchanged_by_the_genome_hook() -> None:
    transcript = _consensus_transcript()
    plain = CouncilEngine(llm_router=None)
    plain._genome = False  # type: ignore[assignment]  # disable the observer
    wired = _engine(GenomeV2())
    assert plain._judge(transcript) == wired._judge(transcript) == ("approve", 0.85)


def test_judge_feeds_the_injected_genome() -> None:
    genome = GenomeV2()
    engine = _engine(genome)
    engine._judge(_consensus_transcript())
    assert {r["agent_id"] for r in genome.rank()} == {"profiler", "analyst", "critic"}
    assert genome.snapshot("profiler")["agreements"] == 1   # type: ignore[index]
    assert genome.snapshot("critic")["dissent"] == 1        # type: ignore[index]


def test_observe_genome_ignores_unknown_members_and_stanceless_rows() -> None:
    genome = GenomeV2()
    engine = _engine(genome)
    engine._observe_genome([
        {"member": "outsider", "response": "[الحكم: موافق]"},
        {"member": "profiler", "response": "بلا حكم"},
        {"member": "analyst", "response": "[الحكم: موافق]"},
    ], "approve")
    assert [r["agent_id"] for r in genome.rank()] == ["analyst"]


def test_observe_genome_noop_when_genome_is_none() -> None:
    engine = _engine(GenomeV2())
    engine._genome = None
    engine._observe_genome(_consensus_transcript(), "approve")  # must not raise


def test_observe_genome_noop_when_import_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CouncilEngine(llm_router=None)
    monkeypatch.setitem(sys.modules, "src.novamind.genome_v2", None)
    assert engine._genome_v2() is None          # sentinel: tried, unavailable
    assert engine._genome is False
    assert engine._genome_v2() is None          # second call must not retry
    engine._observe_genome(_consensus_transcript(), "approve")  # must not raise


def test_observe_genome_swallows_observer_errors() -> None:
    class _Boom:
        def observe_council(self, stances: dict[str, str], verdict: str) -> None:
            raise RuntimeError("boom")

    engine = _engine(_Boom())
    assert engine._judge(_consensus_transcript()) == ("approve", 0.85)


def test_engine_defaults_to_the_shared_genome() -> None:
    reset_genome_v2()
    engine = CouncilEngine(llm_router=None)
    assert engine._genome_v2() is get_genome_v2()
    engine._judge(_consensus_transcript())
    assert get_genome_v2().snapshot("analyst") is not None
