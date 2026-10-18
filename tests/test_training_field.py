"""Field loop (P4) — run → lesson → genome → evolution.

Hermetic: a temp training DB, a temp lesson DB and an **injected genome**, so no
test here touches the process-wide singletons, the real data dir or the network.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from novamind.training import (
    GRADUATION_MIN_SCORE,
    TrainingEngine,
    TrainingStore,
)
from novamind.training.field import (
    FIELD_ENV,
    LESSON_DB_ENV,
    FieldLoop,
    default_lesson_db_path,
    field_enabled,
    get_field_loop,
    lesson_from_run,
    reset_field_loop,
)

pytest.importorskip("learning.lesson_store")
GENOME = pytest.importorskip("novamind.genome_v2")


# ── helpers ──────────────────────────────────────────────────────────────
def _run(agent_id: str, *, certified: bool, steps: int = 3) -> Any:
    """A minimal recorded run for loop-level tests."""
    from novamind.training.models import TrainingRun

    phases = tuple(
        {
            "skill": f"m{i}", "index": i, "hours": 1.0, "min_score": 0.7,
            "source": "plan",
            "score": 0.9 if certified else 0.4,
            "passed": certified,
            "critical": not certified,
        }
        for i in range(steps)
    )
    return TrainingRun(
        run_id=f"tr_test_{agent_id}_{int(certified)}",
        agent_id=agent_id,
        spec="default",
        started_at=1.0,
        finished_at=2.0,
        completion_rate=1.0 if certified else 0.0,
        training_score=0.9 if certified else 0.4,
        gate_score=0.9 if certified else 0.4,
        final_score=0.9 if certified else 0.4,
        verdict="graduated" if certified else "failed",
        certified=certified,
        phases=phases,
        detail={
            "modules_total": steps,
            "modules_passed": steps if certified else 0,
            "critical_failures": [] if certified else ["m0"],
            "min_score": GRADUATION_MIN_SCORE,
        },
    )


def claiming_run(agent_id: str = "coder") -> Any:
    """A run that *claims* readiness (score clears the bar) but is not certified."""
    return replace(
        _run(agent_id, certified=False),
        completion_rate=0.5,
        training_score=0.9,
        final_score=0.62,
        verdict="needs_retraining",
    )


# ── fixtures / helpers ───────────────────────────────────────────────────
@pytest.fixture()
def genome() -> Any:
    """A fresh, isolated genome (never the process-wide singleton)."""
    return GENOME.GenomeV2()


@pytest.fixture()
def loop(tmp_path: Path, genome: Any) -> FieldLoop:
    """A field loop over throwaway databases and an isolated genome."""
    return FieldLoop(lesson_db=tmp_path / "lessons.db", genome=genome)


@pytest.fixture()
def engine(tmp_path: Path, genome: Any) -> TrainingEngine:
    """An engine whose field loop is fully hermetic."""
    eng = TrainingEngine(store=TrainingStore(tmp_path / "t.db"))
    eng._field = FieldLoop(lesson_db=tmp_path / "lessons.db", genome=genome)
    return eng


def partial_claim(agent_id: str, skill: str, index: int, *,
                  quality: float = 0.85, salt: str = "") -> float:
    """Half the curriculum strong, half weak — claims more than it proves.

    The average clears the graduation bar (so the agent "claims" readiness) but
    completion stays under 80%, so the gate refuses to certify it.
    """
    return 0.95 if index < 12 else 0.55


# ── run → lesson ─────────────────────────────────────────────────────────
def test_certified_run_yields_a_success_lesson(engine: TrainingEngine) -> None:
    """A certified run teaches what readiness looks like."""
    run = engine.train("coder", quality=0.95)
    lesson = engine.lessons()[0]
    assert run.certified is True
    assert lesson.source_outcome.value == "success"
    assert "coder" in lesson.principle
    assert f"run:{run.run_id}" in lesson.evidence
    assert lesson.agent_role == "coder"


def test_failing_run_names_the_failing_modules(engine: TrainingEngine) -> None:
    """A critical failure produces a lesson naming the module to fix."""
    engine.evaluator = lambda agent_id, skill, index, *, quality=0.85, salt="": (
        0.30 if index == 0 else 0.95
    )
    run = engine.train("coder")
    lesson = engine.lessons()[0]
    assert run.verdict == "failed"
    assert lesson.source_outcome.value == "failure"
    assert f"critical:{run.detail['critical_failures'][0]}" in lesson.evidence


def test_partial_completion_teaches_completion(engine: TrainingEngine) -> None:
    """Claiming readiness without finishing is a partial-outcome lesson."""
    engine.evaluator = partial_claim
    run = engine.train("coder")
    # Preconditions: the agent claims readiness (its average clears the bar)
    # while the gate refuses to certify it (completion under 80%).
    assert run.training_score >= GRADUATION_MIN_SCORE
    assert run.certified is False
    lesson = engine.lessons()[0]
    assert lesson.source_outcome.value == "partial"
    assert "curriculum" in lesson.principle


def test_repeated_failure_merges_into_one_lesson(engine: TrainingEngine) -> None:
    """The same failure mode consolidates and gains confidence, not twins."""
    engine.evaluator = partial_claim
    for _ in range(4):
        engine.train("coder")
    lessons = engine.lessons()
    assert len(lessons) == 1
    stats = engine.field_stats()
    assert stats["absorbed"] == 4
    assert stats["merged"] == 3
    assert lessons[0].confidence > 0.5


def test_lessons_are_kept_per_agent(engine: TrainingEngine) -> None:
    """Two agents never share a lesson store (no cross-agent attribution)."""
    engine.evaluator = partial_claim
    engine.train("coder")
    engine.train("tester")
    assert len(engine.lessons("coder")) == 1
    assert len(engine.lessons("tester")) == 1
    assert engine.field_stats()["agents_with_lessons"] == 2
    assert len(engine.lessons()) == 2
    assert engine.lessons("unknown") == []


def test_lessons_are_persisted_and_reloaded(tmp_path: Path) -> None:
    """A second loop over the same DB restores the lessons."""
    path = tmp_path / "lessons.db"
    first = FieldLoop(lesson_db=path)
    first.absorb(_run("coder", certified=True))
    assert len(first.lessons()) == 1

    second = FieldLoop(lesson_db=path)
    assert len(second.lessons()) == 1
    assert second.lessons()[0].agent_role == "coder"


def test_lessons_are_listed_most_confident_first(engine: TrainingEngine) -> None:
    """The listing is ordered by confidence for a dashboard."""
    engine.train("coder", quality=0.95)
    engine.evaluator = partial_claim
    engine.train("tester")
    lessons = engine.lessons()
    assert {lesson.agent_role for lesson in lessons} == {"coder", "tester"}
    confidences = [lesson.confidence for lesson in lessons]
    assert confidences == sorted(confidences, reverse=True)
    assert lessons[0].agent_role == "coder"


def test_lesson_listing_is_bounded(loop: FieldLoop) -> None:
    """A caller cannot ask for an unbounded listing."""
    loop.absorb(_run("coder", certified=True))
    assert len(loop.lessons(limit=0)) == 1
    assert len(loop.lessons(limit=10_000)) == 1


# ── lesson → genome ──────────────────────────────────────────────────────
def test_a_certified_run_agrees_with_the_gate(engine: TrainingEngine) -> None:
    """Proving readiness after claiming it is an agreement."""
    engine.train("coder", quality=0.95)
    assert engine.field_stats()["last_tick"]["genome"] == {
        "agent_id": "coder", "claimed": "yes", "truth": "yes", "agreement": True,
    }


def test_a_claimed_but_unproven_run_disagrees(engine: TrainingEngine) -> None:
    """Claiming a readiness the gate refuses is recorded as a dissent."""
    engine.evaluator = partial_claim
    run = engine.train("coder")
    # Precondition: the score claims readiness while the gate refuses it.
    assert run.training_score >= GRADUATION_MIN_SCORE
    assert run.certified is False
    assert engine.field_stats()["last_tick"]["genome"] == {
        "agent_id": "coder", "claimed": "yes", "truth": "no", "agreement": False,
    }


def test_humble_agent_agrees_with_the_gate(loop: FieldLoop, genome: Any) -> None:
    """Not claiming readiness when it cannot prove it is still agreement."""
    loop.observe(_run("weak", certified=False))
    row = genome.snapshot("weak")
    assert row is not None
    assert row["observations"] == 1


def test_observe_is_a_noop_when_the_genome_is_disabled(loop: FieldLoop) -> None:
    """``genome_enabled=False`` keeps the loop away from the genome."""
    quiet = FieldLoop(lesson_db=loop._lesson_db_path, genome_enabled=False)
    assert quiet.observe(_run("coder", certified=True)) is None
    assert quiet.evolve() == []
    assert quiet.stats()["genome_enabled"] is False


# ── genome → evolution ───────────────────────────────────────────────────
def test_a_consistent_overclaimer_is_retrained(loop: FieldLoop, genome: Any) -> None:
    """Enough disagreement drops an agent below probation and mutates it."""
    for _ in range(GENOME.MIN_OBSERVATIONS):
        loop.observe(claiming_run())
    advice = genome.advise("coder")
    assert advice["action"] == "retrain"
    assert advice["fitness"] < GENOME.PROBATION_BELOW

    actions = loop.evolve()
    assert [a["agent_id"] for a in actions if a["mutated"]] == ["coder"]
    assert loop.stats()["mutations"] == 1


def test_mutation_cannot_thrash(loop: FieldLoop) -> None:
    """A mutation resets the evidence, so the next pass has nothing to act on."""
    for _ in range(GENOME.MIN_OBSERVATIONS):
        loop.observe(claiming_run())
    assert loop.evolve()[0]["mutated"] is True

    # Observations were reset by the mutation ⇒ the loop must hold off.
    assert [a["action"] for a in loop.evolve()] == ["observe"]
    assert loop.stats()["mutations"] == 1


def test_evolve_reports_every_observed_agent(loop: FieldLoop, genome: Any) -> None:
    """An evolution pass reports one action per ranked agent."""
    genome.observe("coder", "yes", "yes")
    genome.observe("tester", "yes", "no")
    actions = loop.evolve()
    assert {a["agent_id"] for a in actions} == {"coder", "tester"}
    assert all(a["mutated"] is False for a in actions)
    assert all(a["action"] == "observe" for a in actions)


def test_tick_report_shape(engine: TrainingEngine) -> None:
    """A tick report carries the run, its lesson and the evolution outcome."""
    run = engine.train("coder", quality=0.95)
    report = engine.field_stats()["last_tick"]
    assert report["agent_id"] == "coder"
    assert report["run_id"] == run.run_id
    assert report["verdict"] == "graduated"
    assert report["lesson"]["source_outcome"] == "success"
    assert report["genome"]["agreement"] is True
    assert report["mutated"] == []


# ── genome → standings (the Academy's fitness table) ─────────────────────
def test_fitness_lists_every_agent_best_first(loop: FieldLoop, genome: Any) -> None:
    """Standings are ranked, and each row explains its own number."""
    for _ in range(GENOME.MIN_OBSERVATIONS):
        genome.observe("coder", "yes", "yes")
        genome.observe("tester", "yes", "no")
    rows = loop.fitness()
    assert [r["agent_id"] for r in rows] == ["coder", "tester"]
    top, bottom = rows
    assert top["fitness"] > bottom["fitness"]
    assert top["observations"] == GENOME.MIN_OBSERVATIONS
    assert top["agreements"] + top["dissent"] == GENOME.MIN_OBSERVATIONS
    assert top["status"] == "elite"


def test_fitness_rows_carry_evidence_and_advice(loop: FieldLoop, genome: Any) -> None:
    """Each row explains itself: evidence counts plus the genome's next action."""
    for _ in range(GENOME.MIN_OBSERVATIONS):
        genome.observe("coder", "yes", "no")
    row = loop.fitness()[0]
    assert row["agent_id"] == "coder"
    assert row["fitness"] < GENOME.PROBATION_BELOW
    assert row["status"] == "probationary"
    assert row["observations"] == GENOME.MIN_OBSERVATIONS
    assert row["agreements"] == 0
    assert row["dissent"] == GENOME.MIN_OBSERVATIONS
    assert row["action"] == "retrain"
    assert "probation" in row["reason"]
    assert row["generation"] == 1
    assert row["retired"] is False


def test_fitness_rows_expose_the_task_channel(loop: FieldLoop, genome: Any) -> None:
    """Real task outcomes appear beside the judgement ones (v1.17.0)."""
    genome.observe_outcome("coder", True, duration=2.0, task="one")
    genome.observe_outcome("coder", True, duration=4.0, task="two")
    genome.observe_outcome("coder", False, duration=6.0, task="three")
    row = [r for r in loop.fitness() if r["agent_id"] == "coder"][0]
    assert row["task_observations"] == 3
    assert row["task_successes"] == 2
    assert row["task_rate"] == pytest.approx(2 / 3, abs=1e-4)
    # EWMA, not a mean: the first outcome anchors, then α=0.35 pulls it down
    assert row["task_ewma"] == pytest.approx(0.65, abs=1e-4)
    assert row["task_duration_avg"] == pytest.approx(3.855, abs=1e-3)
    assert row["task_last_ok"] is False
    assert row["task_last_duration"] == pytest.approx(6.0)
    # the judgement channel is untouched by a task run
    assert row["observations"] == 0
    assert row["evidence"] == 3


def test_fitness_evidence_sums_both_channels(loop: FieldLoop, genome: Any) -> None:
    """``evidence`` is the number the advice thresholds actually count."""
    for _ in range(GENOME.MIN_OBSERVATIONS):
        genome.observe("coder", "yes", "yes")
    for _ in range(3):
        genome.observe_outcome("coder", True, duration=1.0)
    row = loop.fitness()[0]
    assert row["observations"] == GENOME.MIN_OBSERVATIONS
    assert row["task_observations"] == 3
    assert row["evidence"] == GENOME.MIN_OBSERVATIONS + 3


def test_fitness_judgement_rows_have_no_task_evidence(
    loop: FieldLoop, genome: Any
) -> None:
    """A council-only agent is honestly reported as untested by tasks."""
    genome.observe("analyst", "yes", "yes")
    row = [r for r in loop.fitness() if r["agent_id"] == "analyst"][0]
    assert row["task_observations"] == 0
    assert row["task_successes"] == 0
    assert row["task_rate"] is None
    assert row["task_ewma"] is None
    assert row["task_duration_avg"] is None
    assert row["task_last_ok"] is None
    assert row["evidence"] == row["observations"]


def test_fitness_tolerates_junk_task_values(tmp_path: Path) -> None:
    """A damaged row renders instead of crashing the dashboard."""
    loop = FieldLoop(lesson_db=tmp_path / "lessons.db")

    class Damaged:
        """A genome whose stored row holds junk in every task field."""

        def rank(self, **kwargs: Any) -> Any:
            return [{
                "agent_id": "coder",
                "observations": "junk",
                "task_successes": float("nan"),
                "task_last_ok": "yes",
                "task_duration_avg": "slow",
            }]

        def advise(self, agent_id: str) -> Any:
            return {"action": "keep", "reason": ""}

    loop._genome = Damaged()
    row = loop.fitness()[0]
    assert row["observations"] == 0
    assert row["task_successes"] == 0
    assert row["task_ewma"] is None
    assert row["task_duration_avg"] is None
    assert row["task_last_ok"] is None
    assert row["evidence"] == 0


def test_fitness_includes_retired_agents(loop: FieldLoop, genome: Any) -> None:
    """A retired agent stays visible (its history is why it was retired)."""
    genome.observe("retired_one", "yes", "yes")
    genome.retire("retired_one", note="test")
    row = [r for r in loop.fitness() if r["agent_id"] == "retired_one"][0]
    assert row["retired"] is True
    assert row["action"] == "revise"


def test_fitness_is_sorted_best_first(loop: FieldLoop, genome: Any) -> None:
    """Ranking is by fitness, so the dashboard needs no client-side sort."""
    for _ in range(GENOME.MIN_OBSERVATIONS):
        genome.observe("good", "yes", "yes")
        genome.observe("bad", "yes", "no")
    rows = loop.fitness()
    values = [r["fitness"] for r in rows]
    assert values == sorted(values, reverse=True)
    assert rows[0]["agent_id"] == "good"


def test_fitness_respects_the_limit(loop: FieldLoop, genome: Any) -> None:
    """The listing limit is clamped, never trusted blindly."""
    for agent in ("a", "b", "c"):
        genome.observe(agent, "yes", "yes")
    assert len(loop.fitness(limit=2)) == 2
    assert len(loop.fitness(limit=0)) == 1
    assert len(loop.fitness(limit=9999)) == 3
    assert len(loop.fitness(limit="2")) == 2  # type: ignore[arg-type]


def test_fitness_is_empty_without_the_genome(loop: FieldLoop) -> None:
    """No genome ⇒ no standings (the dashboard shows an empty state)."""
    quiet = FieldLoop(
        lesson_db=loop._lesson_db_path, genome_enabled=False
    )
    assert quiet.fitness() == []


def test_fitness_is_empty_when_the_genome_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """A genome that cannot be imported degrades to an empty list."""
    loop = FieldLoop(lesson_db=tmp_path / "lessons.db")
    monkeypatch.setattr(loop, "_genome_obj", lambda: None)
    assert loop.fitness() == []


def test_fitness_tolerates_a_broken_genome(tmp_path: Path) -> None:
    """A genome that raises never takes the dashboard down."""
    loop = FieldLoop(lesson_db=tmp_path / "lessons.db")

    class Broken:
        """A genome whose every view raises."""

        def rank(self, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    monkeypatch_loop = loop
    monkeypatch_loop._genome = Broken()
    assert loop.fitness() == []


def test_engine_exposes_fitness(engine: TrainingEngine) -> None:
    """The engine delegates the standings view to its loop."""
    engine.train("coder", quality=0.95)
    rows = engine.fitness()
    assert [r["agent_id"] for r in rows] == ["coder"]
    assert rows[0]["observations"] == 1


def test_engine_fitness_is_empty_when_the_loop_is_off(tmp_path: Path) -> None:
    """``field_loop=False`` ⇒ no standings view."""
    eng = TrainingEngine(
        store=TrainingStore(tmp_path / "t.db"), field_loop=False
    )
    assert eng.fitness() == []


def test_last_tick_is_none_before_any_run(loop: FieldLoop) -> None:
    """An untouched loop reports nothing."""
    assert loop.last_tick() is None
    assert loop.stats()["ticks"] == 0


def test_reset_forgets_everything(loop: FieldLoop) -> None:
    """Reset clears lessons, counters and the last report."""
    loop.absorb(_run("coder", certified=True))
    loop.reset()
    assert loop.lessons() == []
    assert loop.stats()["absorbed"] == 0
    assert loop.last_tick() is None


# ── engine integration ───────────────────────────────────────────────────
def test_engine_can_disable_the_field_loop(tmp_path: Path) -> None:
    """``field_loop=False`` restores the plain P3 genome feed."""
    eng = TrainingEngine(
        store=TrainingStore(tmp_path / "t.db"), field_loop=False, feed_genome=False
    )
    eng.train("coder", quality=0.95)
    assert eng.field_stats() == {}
    assert eng.lessons() == []
    assert eng.evolve() == []


def test_engine_views_delegate_to_the_loop(engine: TrainingEngine) -> None:
    """The engine exposes the loop's lessons, stats and evolution pass."""
    engine.train("coder", quality=0.95)
    assert engine.lessons()[0].agent_role == "coder"
    assert engine.field_stats()["ticks"] == 1
    assert isinstance(engine.evolve(), list)


def test_engine_degrades_without_the_learning_layer(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing learning layer never breaks a training run."""
    eng = TrainingEngine(
        store=TrainingStore(tmp_path / "t.db"), feed_genome=False
    )
    monkeypatch.setattr("novamind.training.field._learning", lambda name: None)
    run = eng.train("coder", quality=0.95)
    assert run.certified is True
    assert eng.field_stats()["absorbed"] == 0
    assert eng.field_stats()["lessons"] == 0


def test_a_failing_lesson_write_never_breaks_the_run(loop: FieldLoop) -> None:
    """A write error is swallowed: the run is the important part."""
    class Boom:
        """A database that refuses to persist."""

        def save(self, lessons: object) -> int:
            raise RuntimeError("disk full")

    loop._database = Boom()
    assert loop.absorb(_run("coder", certified=True)) is not None


# ── lesson construction + config ─────────────────────────────────────────
def test_lesson_from_run_without_the_learning_layer(monkeypatch) -> None:
    """No learning layer ⇒ no lesson (and no exception)."""
    monkeypatch.setattr("novamind.training.field._learning", lambda name: None)
    assert lesson_from_run(_run("coder", certified=True)) is None


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("yes", True), ("on", True), ("", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("OFF", False),
])
def test_field_switch(value: str, expected: bool, monkeypatch) -> None:
    """The master switch defaults to on and accepts the usual spellings."""
    monkeypatch.setenv(FIELD_ENV, value)
    assert field_enabled() is expected


def test_field_switch_defaults_on(monkeypatch) -> None:
    """Unset means enabled."""
    monkeypatch.delenv(FIELD_ENV, raising=False)
    assert field_enabled() is True


def test_default_lesson_db_sits_beside_the_training_db(
    tmp_path: Path, monkeypatch
) -> None:
    """A loop beside a training DB keeps its lessons beside it (hermetic)."""
    monkeypatch.delenv(LESSON_DB_ENV, raising=False)
    assert (
        default_lesson_db_path(tmp_path / "t.db") == tmp_path / "lessons.db"
    )


def test_lesson_db_env_wins(tmp_path: Path, monkeypatch) -> None:
    """``$NEXUS_TRAINING_LESSONS_DB`` overrides the derived path."""
    monkeypatch.setenv(LESSON_DB_ENV, str(tmp_path / "explicit.db"))
    assert default_lesson_db_path(tmp_path / "t.db") == tmp_path / "explicit.db"


def test_stats_expose_the_lesson_database(tmp_path: Path) -> None:
    """Stats tell an operator where the lessons live."""
    loop = FieldLoop(lesson_db=tmp_path / "lessons.db")
    assert loop.stats()["database"] == str(tmp_path / "lessons.db")


def test_stats_hide_the_database_when_there_is_none() -> None:
    """A loop without persistence reports no database."""
    loop = FieldLoop()
    assert loop.stats()["database"] is None


def test_get_field_loop_is_a_singleton(monkeypatch, tmp_path: Path) -> None:
    """The process-wide loop is shared, and its DB is env-configurable."""
    monkeypatch.setenv(LESSON_DB_ENV, str(tmp_path / "shared.db"))
    reset_field_loop()
    try:
        assert get_field_loop() is get_field_loop()
    finally:
        reset_field_loop()


def test_get_field_loop_with_kwargs_is_fresh(tmp_path: Path) -> None:
    """Passing kwargs always returns an unshared loop (hermetic tests)."""
    one = get_field_loop(lesson_db=tmp_path / "a.db")
    two = get_field_loop(lesson_db=tmp_path / "a.db")
    assert one is not two


# ── one genome per process ───────────────────────────────────────────────
def test_the_loop_and_the_council_share_one_genome() -> None:
    """اسم واحد ⇒ جينوم واحد.

    يُستورد ``genome_v2`` تحت اسمين ممكنين (``novamind.genome_v2`` و
    ``src.novamind.genome_v2``)؛ فإن استورد كلُّ نظامٍ صيغتَه صار **نسختين
    لا تلتقيان أبداً**. هذا الاختبار يثبّت أن الميدان (قناة المهمّة) والمجلس
    (قناة الحُكم) يقرأان ويغذّيان نفس الوحدة — وإلا فلا دمج أصلاً.
    """
    from src.council.engine import CouncilEngine
    from src.novamind.genome_v2 import get_genome_v2 as canonical

    shared = canonical()
    assert FieldLoop()._genome_obj() is shared
    assert CouncilEngine(llm_router=object())._genome_v2() is shared


