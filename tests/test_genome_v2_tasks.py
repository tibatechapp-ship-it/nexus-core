"""Tests for the P4.5 second result source — task outcomes in genome v2.

The council channel (``observe``) is covered by ``test_genome_v2.py``; this
suite covers the *task* channel the 20 framework agents use: success/failure +
duration + gate quality folded into the same agent row, confidence-blended
into the headline fitness.  Hermetic like the rest of the genome: stdlib only,
no network, no clock, no disk.

The central contract: **no task observations ⇒ byte-identical to v1.14.0**.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.core.types import AgentResult
from src.council.engine import CouncilEngine
from src.novamind import genome_v2 as gv
from src.novamind.genome_v2 import (
    CONFIDENCE_K,
    FINAL_VERDICTS,
    HISTORY_LIMIT,
    MIN_OBSERVATIONS,
    NEUTRAL_FITNESS,
    GenomeV2,
    blend_fitness,
    confidence,
    empty_genome,
    evidence,
    fitness,
    reset_genome_v2,
)


# ══ pure helpers ═════════════════════════════════════════════════════════════
def test_every_exported_name_resolves() -> None:
    """`__all__` must only list real module attributes (guards F822-class bugs)."""
    missing = [name for name in gv.__all__ if not hasattr(gv, name)]
    assert missing == []


@pytest.mark.parametrize("row,expected", [
    ({}, 0),
    ({"observations": 7}, 7),
    ({"task_observations": 4}, 4),
    ({"observations": 7, "task_observations": 4}, 11),
    ({"observations": None, "task_observations": None}, 0),
])
def test_evidence_counts_both_sources(row: dict[str, Any], expected: int) -> None:
    assert evidence(row) == expected


def test_evidence_on_a_council_row_equals_observations() -> None:
    """Pre-P4.5 rows have no task key — evidence must equal observations."""
    row = empty_genome("analyst")
    row["observations"] = 9
    assert evidence(row) == row["observations"] == 9


def test_blend_without_task_confidence_is_exactly_the_judgement() -> None:
    """task_conf == 0 ⇒ round(judgement, 4) — the back-compat promise."""
    for value in (0.0, 0.1471, 0.5, 0.7727, 1.0):
        assert blend_fitness(value, 0.8, 0.0, 0.0) == round(value, 4)


def test_blend_with_no_evidence_on_either_side_is_neutral() -> None:
    assert blend_fitness(NEUTRAL_FITNESS, 0.0, NEUTRAL_FITNESS, 0.0) == NEUTRAL_FITNESS


def test_blend_weights_by_confidence_not_symmetrically() -> None:
    # judgement side carries far more evidence → it dominates
    blended = blend_fitness(1.0, confidence(50), 0.0, confidence(1))
    assert blended > 0.8
    # …and the mirror: heavy failing judgement outweighs one lucky task
    mirrored = blend_fitness(0.0, confidence(50), 1.0, confidence(1))
    assert mirrored < 0.2


def test_blend_of_perfect_and_failing_equal_evidence_is_neutral() -> None:
    n = 12
    assert blend_fitness(fitness(n, 1.0), confidence(n),
                         fitness(n, 0.0), confidence(n)) == pytest.approx(0.5, abs=0.001)


def test_empty_genome_has_the_task_fields() -> None:
    row = empty_genome("coder")
    assert row["task_observations"] == 0 and row["task_successes"] == 0
    assert row["task_ewma"] == NEUTRAL_FITNESS
    assert row["task_duration_avg"] is None and row["task_last_ok"] is None
    assert row["task_last_duration"] is None and row["task_last_quality"] is None


# ══ observe_outcome — the task channel ═══════════════════════════════════════
def test_success_and_failure_counters() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True)
    g.observe_outcome("coder", False)
    g.observe_outcome("coder", True)
    row = g.snapshot("coder")
    assert row["task_observations"] == 3  # type: ignore[index]
    assert row["task_successes"] == 2  # type: ignore[index]
    assert row["task_last_ok"] is True  # type: ignore[index]


def test_first_outcome_anchors_the_task_ewma() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True)
    assert g.snapshot("coder")["task_ewma"] == 1.0  # type: ignore[index]
    g.observe_outcome("coder", False)
    expected = round((1 - 0.35) * 1.0 + 0.35 * 0.0, 6)
    assert g.snapshot("coder")["task_ewma"] == expected  # type: ignore[index]


def test_a_failure_is_always_a_zero_sample_even_with_a_high_quality() -> None:
    """Ground truth wins: a failed task can never raise fitness."""
    g = GenomeV2()
    g.observe_outcome("coder", False, quality=0.9)
    row = g.snapshot("coder")
    assert row["task_ewma"] == 0.0  # type: ignore[index]
    assert row["task_last_quality"] == 0.9  # type: ignore[index]  # still recorded
    assert float(row["fitness"]) < NEUTRAL_FITNESS  # type: ignore[index]


def test_quality_refines_a_success() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, quality=0.6)
    assert g.snapshot("coder")["task_ewma"] == 0.6  # type: ignore[index]


def test_a_bare_success_samples_full_marks() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True)
    assert g.snapshot("coder")["task_ewma"] == 1.0  # type: ignore[index]
    assert g.snapshot("coder")["task_last_quality"] is None  # type: ignore[index]


def test_duration_is_recorded_as_an_ewma_but_never_scored() -> None:
    timed, untimed = GenomeV2(), GenomeV2()
    for _ in range(6):
        timed.observe_outcome("coder", True, duration=2.0)
        untimed.observe_outcome("coder", True)
    timed.observe_outcome("coder", True, duration=6.0)
    untimed.observe_outcome("coder", True)

    row = timed.snapshot("coder")
    expected_avg = round((1 - 0.35) * 2.0 + 0.35 * 6.0, 4)
    assert row["task_duration_avg"] == expected_avg  # type: ignore[index]
    # identical fitness: speed is not correctness
    assert row["fitness"] == untimed.snapshot("coder")["fitness"]  # type: ignore[index]


def test_duration_stats_survive_the_ewma_helpers_junk() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, duration="fast")   # type: ignore[arg-type]  # junk on purpose
    row = g.snapshot("coder")
    assert row["task_duration_avg"] is None  # type: ignore[index]
    assert row["task_last_duration"] is None  # type: ignore[index]
    g.observe_outcome("coder", True, duration=-3.0)     # clamped, never negative
    assert g.snapshot("coder")["task_last_duration"] == 0.0  # type: ignore[index]


def test_junk_quality_is_recorded_as_none_and_a_success_still_scores() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, quality="excellent")  # type: ignore[arg-type]  # junk
    row = g.snapshot("coder")
    assert row["task_last_quality"] is None  # type: ignore[index]
    assert row["task_ewma"] == 1.0  # type: ignore[index]


def test_task_channel_never_touches_judgement_fields() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, duration=1.0, quality=0.8, task="build")
    row = g.snapshot("coder")
    assert row["observations"] == 0 and row["agreements"] == 0  # type: ignore[index]
    assert row["last_stance"] is None and row["last_final"] is None  # type: ignore[index]
    assert set(row["traits"]) == set(FINAL_VERDICTS)  # type: ignore[index]


def test_task_history_event_shape_and_label() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, duration=1.5, quality=0.9, task="lint")
    event = g.snapshot("coder")["history"][-1]  # type: ignore[index]
    assert event == {"seq": 1, "event": "task", "ok": True,
                     "duration": 1.5, "quality": 0.9, "task": "lint"}


def test_task_history_is_bounded() -> None:
    g = GenomeV2()
    for _ in range(HISTORY_LIMIT + 10):
        g.observe_outcome("coder", True)
    history = g.snapshot("coder")["history"]  # type: ignore[index]
    assert len(history) == HISTORY_LIMIT
    assert history[-1]["seq"] == HISTORY_LIMIT + 10


# ══ blended fitness & standing ═══════════════════════════════════════════════
def test_council_only_rows_stay_byte_identical_to_v1() -> None:
    """No task source ever called ⇒ stored fitness is exactly the v1.14.0 value."""
    g = GenomeV2()
    for i in range(10):
        g.observe("analyst", "yes", "approve" if i % 2 else "reject")
    row = g.snapshot("analyst")
    assert row["fitness"] == fitness(int(row["observations"]), float(row["ewma"]))  # type: ignore[index]
    assert row["task_observations"] == 0  # type: ignore[index]


def test_task_only_agent_gets_a_standing_without_any_council() -> None:
    g = GenomeV2()
    for _ in range(12):
        g.observe_outcome("coder", True)
    row = g.snapshot("coder")
    assert row["observations"] == 0  # type: ignore[index]
    assert float(row["fitness"]) > 0.75 and row["status"] == "elite"  # type: ignore[index]


def test_both_sources_blend_by_confidence() -> None:
    g = GenomeV2()
    for _ in range(12):
        g.observe("analyst", "yes", "approve")       # perfect judgement
        g.observe_outcome("analyst", False)          # failing its tasks
    row = g.snapshot("analyst")
    n = 12
    expected = blend_fitness(fitness(n, 1.0), confidence(n),
                             fitness(n, 0.0), confidence(n))
    assert row["fitness"] == expected == pytest.approx(0.5, abs=0.001)  # type: ignore[index]


def test_a_failing_task_outcome_pulls_an_elite_council_member_down() -> None:
    g = GenomeV2()
    for _ in range(12):
        g.observe("analyst", "yes", "approve")
    before = float(g.snapshot("analyst")["fitness"])  # type: ignore[index]
    for _ in range(12):
        g.observe_outcome("analyst", False)
    after = float(g.snapshot("analyst")["fitness"])  # type: ignore[index]
    assert after < before


def test_status_reclassifies_after_task_outcomes() -> None:
    g = GenomeV2()
    g.ensure("coder")
    assert g.snapshot("coder")["status"] == "stable"  # type: ignore[index]
    for _ in range(12):
        g.observe_outcome("coder", True)
    assert g.snapshot("coder")["status"] == "elite"  # type: ignore[index]


# ══ observe_result — the AgentResult bridge ══════════════════════════════════
def test_observe_result_accepts_a_real_agent_result() -> None:
    g = GenomeV2()
    result = AgentResult(agent="tester", ok=True, output="green", duration_s=1.25)
    snapshot = g.observe_result(result, quality=0.95, task="gate")
    assert snapshot is not None and snapshot["agent_id"] == "tester"
    assert snapshot["task_observations"] == 1
    assert snapshot["task_last_duration"] == 1.25
    assert snapshot["task_last_quality"] == 0.95


def test_observe_result_folds_a_failure() -> None:
    g = GenomeV2()
    result = AgentResult(agent="tester", ok=False, error="boom", duration_s=0.4)
    snapshot = g.observe_result(result)
    assert snapshot is not None and snapshot["task_last_ok"] is False
    assert snapshot["task_ewma"] == 0.0


def test_observe_result_refuses_unscorable_input() -> None:
    """No agent id or no ok flag ⇒ None, and the registry stays clean."""
    g = GenomeV2()
    assert g.observe_result(SimpleNamespace(ok=True)) is None
    assert g.observe_result(SimpleNamespace(agent="x")) is None
    assert g.observe_result(object()) is None
    assert g.to_dict()["agents"] == {}


def test_module_level_observe_result_targets_the_shared_genome() -> None:
    genome = reset_genome_v2()
    result = AgentResult(agent="analyst", ok=True, duration_s=0.1)
    snapshot = gv.observe_result(result)
    assert snapshot is not None
    assert genome.snapshot("analyst")["task_observations"] == 1  # type: ignore[index]


def test_module_level_observe_result_accepts_an_explicit_genome() -> None:
    target = GenomeV2()
    result = AgentResult(agent="analyst", ok=True)
    snapshot = gv.observe_result(result, genome=target)
    assert snapshot is not None
    assert target.snapshot("analyst")["task_observations"] == 1  # type: ignore[index]
    assert reset_genome_v2().snapshot("analyst") is None  # shared genome untouched


# ══ advise / rank / stats read the second source ═════════════════════════════
def test_advise_promotes_a_task_only_agent() -> None:
    """Thresholds count evidence, not just council observations."""
    g = GenomeV2()
    for _ in range(12):
        g.observe_outcome("coder", True)
    advice = g.advise("coder")
    assert advice["action"] == "promote"
    assert advice["observations"] == 0          # council count is still reported…
    assert advice["evidence"] == 12             # …and the threshold used evidence


def test_advise_retrains_a_failing_task_only_agent() -> None:
    g = GenomeV2()
    for _ in range(12):
        g.observe_outcome("coder", False)
    assert g.advise("coder")["action"] == "retrain"


def test_advise_observes_until_evidence_clears_the_bar() -> None:
    g = GenomeV2()
    for _ in range(MIN_OBSERVATIONS - 1):
        g.observe_outcome("coder", True)
    assert g.advise("coder")["action"] == "observe"
    g.observe_outcome("coder", True)
    assert g.advise("coder")["action"] == "promote"


def test_advise_unknown_agent_reports_zero_evidence() -> None:
    advice = GenomeV2().advise("ghost")
    assert advice["action"] == "unknown" and advice["evidence"] == 0


def test_rank_tie_break_prefers_total_evidence() -> None:
    g = GenomeV2()
    # equal fitness; aaa earned its record purely from tasks, bbb from council
    aaa, bbb = g.ensure("aaa"), g.ensure("bbb")
    aaa["fitness"] = bbb["fitness"] = 0.7
    aaa["task_observations"] = 10                 # evidence 10, observations 0
    bbb["observations"] = 5                       # evidence 5
    assert [r["agent_id"] for r in g.rank()] == ["aaa", "bbb"]


def test_stats_reports_task_observations() -> None:
    g = GenomeV2()
    g.observe("analyst", "yes", "approve")
    for _ in range(4):
        g.observe_outcome("coder", True)
    stats = g.stats()
    assert stats["observations"] == 1
    assert stats["task_observations"] == 4
    assert GenomeV2().stats()["task_observations"] == 0


# ══ persistence ══════════════════════════════════════════════════════════════
def test_round_trip_preserves_task_fields() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, duration=2.0, quality=0.8, task="build")
    g.observe_outcome("coder", False)
    restored = GenomeV2.from_dict(g.to_dict())
    assert restored.snapshot("coder") == g.snapshot("coder")
    assert restored.stats() == g.stats()


def test_a_pre_p45_payload_loads_with_task_defaults() -> None:
    """A v1.14.0 dict (rows without task keys) must load unchanged."""
    old_row = {k: v for k, v in empty_genome("analyst").items()
               if not k.startswith("task_")}
    old_row["observations"] = 6
    old_row["fitness"] = fitness(6, 1.0)
    restored = GenomeV2.from_dict({"version": 2, "alpha": 0.35, "seq": 3,
                                   "agents": {"analyst": old_row}})
    row = restored.snapshot("analyst")
    assert row["task_observations"] == 0  # type: ignore[index]
    assert row["task_ewma"] == NEUTRAL_FITNESS  # type: ignore[index]
    assert row["fitness"] == fitness(6, 1.0)  # type: ignore[index]  # migration left it
    # …and the restored genome accepts new task observations on top
    restored.observe_outcome("analyst", True)
    assert restored.snapshot("analyst")["task_observations"] == 1  # type: ignore[index]


def test_mutate_resets_the_task_channel() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True, duration=1.0)
    fresh = g.mutate("coder", note="retrain")
    assert fresh["task_observations"] == 0 and fresh["task_successes"] == 0
    assert fresh["task_ewma"] == NEUTRAL_FITNESS
    assert fresh["task_duration_avg"] is None and fresh["task_last_ok"] is None


# ══ council engine wiring stays inert for the task channel ═══════════════════
def test_engine_debate_still_records_only_judgements() -> None:
    g = GenomeV2()
    engine = CouncilEngine(llm_router=None, genome=g)
    verdict, score = engine._judge(
        [_entry("profiler", "yes"), _entry("analyst", "yes"),
         _entry("critic", "no"), _entry("visionary", "yes"),
         _entry("pragmatist", "yes"), _entry("expert", "yes")],
    )
    assert verdict in ("approve", "reject", "human_review") and score >= 0.0
    stats = g.stats()
    assert stats["observations"] > 0 and stats["task_observations"] == 0


def _entry(member: str, stance: str) -> dict[str, Any]:
    word = {"yes": "موافق", "no": "مرفوض", "mid": "محايد"}[stance]
    return {"member": member, "response": f"تحليل … [الحكم: {word}]"}


# the confidence knob is shared by both channels — pin the coupling
def test_task_channel_uses_the_same_confidence_shrinkage() -> None:
    g = GenomeV2()
    g.observe_outcome("coder", True)
    # one lucky success must NOT look elite (k = CONFIDENCE_K)
    assert float(g.snapshot("coder")["fitness"]) < 0.6  # type: ignore[index]
    assert confidence(1) == pytest.approx(1 / (1 + CONFIDENCE_K), abs=1e-6)
