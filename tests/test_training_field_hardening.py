"""Hardening suite for the *field loop* (P4).

The field loop is the part that must never take a training run down: it sits on
the hot path of every run (`tick` = absorb + observe + evolve) and it reaches
three optional layers (the lesson store, the genome, the learning package).  So
this suite attacks exactly that:

* **degradation** — every optional layer is removed, broken, or returns junk,
  and the loop must still absorb the lesson and answer;
* **the evolution safety property** — a ``retrain`` mutation resets the agent's
  observations, so the same agent cannot be mutated twice without fresh
  evidence (no thrash);
* **per-agent isolation** — one agent's lesson never leaks into another's;
* **durability + concurrency** — lessons survive a reopen; parallel ticks lose
  neither a lesson nor a counter;
* **hostile input** — junk limits, junk agent ids, junk genome rows.

Hermetic: temp databases and an injected genome — no process-wide singleton, no
real data dir, no network.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

from novamind.training import GRADUATION_MIN_SCORE
from novamind.training.models import TrainingRun

field_mod = pytest.importorskip("novamind.training.field")
pytest.importorskip("learning.lesson_store")
GENOME = pytest.importorskip("novamind.genome_v2")

FieldLoop = field_mod.FieldLoop
_MAX_LIMIT = field_mod._MAX_LIMIT
_MIN_LIMIT = field_mod._MIN_LIMIT


class _FakeAdviceGenome:
    """A genome whose ``rank`` works but whose ``advise`` raises."""

    def __init__(self, *, row: Dict[str, Any] | None = None) -> None:
        self.row = row or {"agent_id": "coder", "fitness": 0.5}

    def rank(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return [dict(self.row)]

    def advise(self, agent_id: str) -> Dict[str, Any]:
        raise RuntimeError("advice is unavailable")

    def stats(self) -> Dict[str, Any]:
        raise RuntimeError("stats are unavailable")


# ── helpers ──────────────────────────────────────────────────────────────
def _phases(*, passed: bool, steps: int = 3) -> tuple[Dict[str, Any], ...]:
    return tuple(
        {
            "skill": f"m{i}", "index": i, "hours": 1.0, "min_score": 0.7,
            "source": "plan", "score": 0.9 if passed else 0.4,
            "passed": passed, "critical": not passed,
        }
        for i in range(steps)
    )


def _run(agent_id: str = "coder", *, run_id: str | None = None,
         certified: bool = False, passed: bool = False,
         training_score: float = 0.4, completion: float = 0.0,
         detail: Dict[str, Any] | None = None) -> TrainingRun:
    """A recorded run with just enough evidence to distil a lesson."""
    base_detail: Dict[str, Any] = {
        "modules_total": 3, "modules_passed": 3 if passed else 0,
        "critical_failures": [] if passed else ["m0"],
        "min_score": GRADUATION_MIN_SCORE,
    }
    if detail:
        base_detail.update(detail)
    return TrainingRun(
        run_id=run_id or f"tr_{agent_id}_{training_score}",
        agent_id=agent_id, spec="default",
        started_at=1.0, finished_at=2.0,
        completion_rate=1.0 if passed else completion,
        training_score=training_score,
        gate_score=training_score, final_score=training_score,
        verdict="graduated" if certified else "needs_retraining",
        certified=certified,
        phases=_phases(passed=passed),
        detail=base_detail,
    )


def _loop(tmp_path: Path, *, genome: Any = None,
          genome_enabled: bool = True, db: bool = True) -> Any:
    return FieldLoop(
        genome=genome,
        lesson_db=(tmp_path / "lessons.db") if db else None,
        genome_enabled=genome_enabled,
    )


def _dissenting_genome(agent_id: str = "planner", rounds: int = 6) -> Any:
    """A genome pushed into probation: the agent claims readiness and misses."""
    genome = GENOME.GenomeV2()
    for _ in range(rounds):
        genome.observe(agent_id, "yes", "no")
    return genome


# ── 1. the master switch and the listing bounds ───────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("0", False), ("false", False), ("no", False), ("off", False),
    ("OFF", False), ("  off  ", False), ("False", False),
    ("1", True), ("on", True), ("yes", True), ("", True), ("junk", True),
])
def test_the_master_switch_parses_its_environment(
    raw: str, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`NEXUS_TRAINING_FIELD` must be forgiving, not strict."""
    monkeypatch.setenv(field_mod.FIELD_ENV, raw)
    assert field_mod.field_enabled() is expected


def test_the_switch_defaults_to_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(field_mod.FIELD_ENV, raising=False)
    assert field_mod.field_enabled() is True


@pytest.mark.parametrize("raw,expected", [
    (0, _MIN_LIMIT), (-5, _MIN_LIMIT), (10_000, _MAX_LIMIT),
    ("7", 7), (3.9, 3), (None, _MAX_LIMIT), ("junk", _MAX_LIMIT),
])
def test_listing_limits_are_clamped_never_rejected(raw: Any, expected: int) -> None:
    """A junk limit must not raise and must not uncap the listing."""
    assert field_mod._clamp_limit(raw) == expected


# ── 2. degradation: every optional layer removed or broken ───────────────
def test_a_missing_learning_package_yields_no_lesson(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the learning layer a run distils to nothing — not to a crash."""
    class _Missing:
        @staticmethod
        def import_module(name: str) -> Any:
            raise ImportError(name)

    monkeypatch.setattr(field_mod, "importlib", _Missing())
    assert field_mod.lesson_from_run(_run()) is None


def test_a_broken_learning_package_is_treated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-ImportError explosion while importing must also degrade."""
    class _Exploding:
        @staticmethod
        def import_module(name: str) -> Any:
            raise RuntimeError("boom")

    monkeypatch.setattr(field_mod, "importlib", _Exploding())
    assert field_mod.lesson_from_run(_run()) is None


def test_an_unopenable_lesson_database_still_lets_a_run_be_absorbed(
    tmp_path: Path,
) -> None:
    """A bad DB path must cost persistence, not the lesson."""
    blocked = tmp_path / "not-a-file"
    blocked.mkdir()

    loop = FieldLoop(genome=GENOME.GenomeV2(), lesson_db=blocked)

    stored = loop.absorb(_run("coder"))

    assert stored is not None
    assert loop.stats()["absorbed"] == 1
    assert len(loop.lessons("coder")) == 1


def test_absorb_returns_none_when_there_is_no_store(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """No store (lesson layer gone): nothing is recorded — and nothing breaks."""
    loop = _loop(tmp_path)
    monkeypatch.setattr(FieldLoop, "_store_for", lambda self, agent_id: None)

    assert loop.absorb(_run("coder")) is None
    assert loop.stats()["absorbed"] == 0


def test_observe_without_a_genome_is_a_no_op(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop(tmp_path)
    monkeypatch.setattr(FieldLoop, "_genome_obj", lambda self: None)

    assert loop.observe(_run("coder")) is None
    assert loop.evolve() == []
    assert loop.fitness() == []


def test_a_disabled_genome_leaves_the_lessons_alone(tmp_path: Path) -> None:
    """`genome_enabled=False` is the hermetic switch: lessons yes, genome no."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2(), genome_enabled=False)

    report = loop.tick(_run("coder"))

    assert report["genome"] is None
    assert report["evolved"] == [] and report["mutated"] == []
    assert loop.stats()["absorbed"] == 1
    assert len(loop.lessons("coder")) == 1


def test_a_genome_that_raises_never_breaks_a_training_run(tmp_path: Path) -> None:
    """The genome is optional infrastructure: a broken one must stay silent."""
    class _BrokenGenome:
        def observe(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("genome down")

        def rank(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("genome down")

        def advise(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("genome down")

    loop = _loop(tmp_path, genome=_BrokenGenome())

    report = loop.tick(_run("coder"))
    assert report["genome"] is None          # observe swallowed
    assert loop.fitness() == []              # rank swallowed
    assert report["mutated"] == []


def test_a_genome_that_refuses_a_mutation_is_reported_not_raised(
    tmp_path: Path,
) -> None:
    """`mutate()` failing must leave the advice visible and `mutated=False`."""
    class _StubbornGenome:
        def observe(self, *args: Any, **kwargs: Any) -> Any:
            return None

        def rank(self, *args: Any, **kwargs: Any) -> Any:
            return [{"agent_id": "planner", "fitness": 0.1}]

        def advise(self, agent_id: str) -> Dict[str, Any]:
            return {"agent_id": agent_id, "action": "retrain", "fitness": 0.1,
                    "observations": 9, "reason": "probation"}

        def mutate(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("read-only genome")

    loop = _loop(tmp_path, genome=_StubbornGenome())

    actions = loop.evolve()
    assert [a["action"] for a in actions] == ["retrain"]
    assert actions[0]["mutated"] is False
    assert loop.stats()["mutations"] == 0


def test_junk_rows_from_the_genome_are_ignored_not_rendered(tmp_path: Path) -> None:
    """A genome row without an agent id is unusable — skip it, keep the rest."""
    class _JunkGenome:
        def observe(self, *args: Any, **kwargs: Any) -> Any:
            return None

        def rank(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
            return [
                {"agent_id": "", "fitness": 0.9},
                {"fitness": 0.8},
                {"agent_id": "coder", "fitness": 0.7, "status": "stable",
                 "observations": 4, "agreements": 3, "dissent": 1},
            ]

        def advise(self, agent_id: str) -> Dict[str, Any]:
            return {}

    loop = _loop(tmp_path, genome=_JunkGenome())

    rows = loop.fitness()
    assert [r["agent_id"] for r in rows] == ["coder"]
    # Missing keys fall back to the neutral values instead of KeyError.
    assert rows[0]["action"] == "unknown" or rows[0]["action"] == ""
    assert rows[0]["fitness"] == 0.7


def test_a_lesson_without_a_to_dict_view_still_serialises() -> None:
    """The API view must never assume the learning layer's object shape."""
    class _Bare:
        id = "L1"
        principle = "p"
        confidence = 0.6
        agent_role = "coder"

    view = field_mod._lesson_view(_Bare())
    assert view == {"id": "L1", "principle": "p", "confidence": 0.6,
                    "agent_role": "coder"}
    assert field_mod._lesson_view(None) is None


# ── 3. per-agent isolation and merge behaviour ───────────────────────────
def test_lessons_never_leak_between_agents(tmp_path: Path) -> None:
    """One store per agent — a merge must stay inside its own agent."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())

    loop.absorb(_run("coder"))
    loop.absorb(_run("planner"))

    assert len(loop.lessons("coder")) == 1
    assert len(loop.lessons("planner")) == 1
    assert {str(lesson.agent_role) for lesson in loop.lessons()} == {"coder", "planner"}


def test_a_repeated_failure_merges_instead_of_multiplying(tmp_path: Path) -> None:
    """The same failure mode consolidates: confidence grows, count does not."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())

    first = loop.absorb(_run("coder", run_id="tr_1"))
    for i in range(2, 6):
        loop.absorb(_run("coder", run_id=f"tr_{i}"))

    stored = loop.lessons("coder")
    assert len(stored) == 1
    assert stored[0].confidence >= float(first.confidence)
    assert loop.stats()["absorbed"] == 5
    assert loop.stats()["merged"] >= 1


def test_a_recovered_agent_is_not_taught_the_failure_lesson(tmp_path: Path) -> None:
    """A passing run must not read as a failure — different lesson entirely."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())

    failed = loop.absorb(_run("coder", run_id="tr_f"))
    passed = loop.absorb(_run("coder", run_id="tr_p", passed=True,
                              certified=True, training_score=0.93))

    assert failed is not None and passed is not None
    assert str(failed.principle) != str(passed.principle)


# ── 4. the evolution safety property (no thrash) ─────────────────────────
def test_a_retrain_mutation_cannot_repeat_without_fresh_evidence(
    tmp_path: Path,
) -> None:
    """Mutation resets the observations — the cooldown that stops thrash."""
    genome = _dissenting_genome("planner")
    loop = _loop(tmp_path, genome=genome)

    first = loop.evolve()
    mutated = [a["agent_id"] for a in first if a["mutated"]]
    assert mutated == ["planner"], "a probationary agent must be re-trained"
    assert loop.stats()["mutations"] == 1

    # Immediately afterwards: the evidence is gone, so there is nothing to act
    # on again. This is the property that makes unattended evolution safe.
    second = loop.evolve()
    assert [a for a in second if a["mutated"]] == []
    assert loop.stats()["mutations"] == 1

    # Fresh dissenting evidence re-arms it — evolution is not permanently off.
    for _ in range(6):
        genome.observe("planner", "yes", "no")
    third = loop.evolve()
    assert [a["agent_id"] for a in third if a["mutated"]] == ["planner"]
    assert loop.stats()["mutations"] == 2


def test_the_mutation_log_is_bounded(tmp_path: Path) -> None:
    """The log cannot grow without limit over a long-lived service."""
    loop = _loop(tmp_path, genome=_dissenting_genome("planner"))
    loop._mutations.extend(f"a{i}" for i in range(_MAX_LIMIT + 200))

    loop.evolve()

    assert len(loop._mutations) <= _MAX_LIMIT


# ── 5. durability and concurrency ────────────────────────────────────────
def test_lessons_survive_a_reopen(tmp_path: Path) -> None:
    """A restarted service must find yesterday's lessons."""
    db = tmp_path / "lessons.db"
    first = FieldLoop(genome=GENOME.GenomeV2(), lesson_db=db)
    first.absorb(_run("coder"))
    first.absorb(_run("planner"))

    reopened = FieldLoop(genome=GENOME.GenomeV2(), lesson_db=db)

    assert len(reopened.lessons("coder")) == 1
    assert len(reopened.lessons("planner")) == 1


def test_parallel_ticks_lose_nothing(tmp_path: Path) -> None:
    """The API is concurrent: counters and lessons must stay exact."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())
    agents = ["coder", "planner", "analyst", "critic"]

    def _work(index: int) -> None:
        loop.tick(_run(agents[index % len(agents)], run_id=f"tr_{index}"))

    threads = [threading.Thread(target=_work, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = loop.stats()
    assert stats["absorbed"] == 40
    assert sum(len(loop.lessons(a)) for a in agents) == 4  # one per agent, merged


def test_the_loop_survives_many_ticks(tmp_path: Path) -> None:
    """A generous floor: only a real regression (locking, DB) can trip it."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())
    for i in range(200):
        loop.tick(_run("coder", run_id=f"tr_{i}"))
    assert loop.stats()["absorbed"] == 200
    assert len(loop.lessons("coder")) == 1


# ── 6. the tick report contract (what the API/UI render) ─────────────────
def test_the_tick_report_has_the_shape_the_api_promises(tmp_path: Path) -> None:
    genome = _dissenting_genome("planner")
    loop = _loop(tmp_path, genome=genome)

    # A run that *claims* readiness and is not certified: the dissent that keeps
    # the agent in probation and makes the evolution pass act.
    report = loop.tick(_run("planner", training_score=0.9))

    assert set(report) == {"agent_id", "run_id", "verdict", "lesson",
                           "genome", "evolved", "mutated"}
    assert report["agent_id"] == "planner"
    assert report["lesson"] is not None
    assert set(report["genome"]) == {"agent_id", "claimed", "truth", "agreement"}
    assert report["genome"]["agreement"] is False
    assert report["mutated"] == ["planner"]
    assert all(a["action"] != "keep" for a in report["evolved"])
    assert loop.stats()["ticks"] == 1


def test_an_honest_failure_is_not_an_evolution_trigger(tmp_path: Path) -> None:
    """A run that admits it failed agrees with the gate — do not re-train it.

    Evolution reacts to *dishonesty* (claimed ready, was not), not to failure:
    otherwise a genuinely weak agent would be mutated on every honest attempt.
    """
    genome = _dissenting_genome("planner")
    loop = _loop(tmp_path, genome=genome)

    report = loop.tick(_run("planner", training_score=0.4, certified=False))

    assert report["genome"] == {"agent_id": "planner", "claimed": "no",
                                "truth": "no", "agreement": True}
    assert report["mutated"] == []
    assert loop.stats()["mutations"] == 0


def test_the_genome_sees_the_claim_against_the_truth(tmp_path: Path) -> None:
    """A confident-but-failed run is the signal that makes the genome useful."""
    genome = GENOME.GenomeV2()
    loop = _loop(tmp_path, genome=genome)

    dishonest = loop.observe(_run("coder", training_score=0.9, certified=False))
    honest = loop.observe(_run("coder", training_score=0.9, certified=True))

    assert dishonest == {"agent_id": "coder", "claimed": "yes", "truth": "no",
                         "agreement": False}
    assert honest is not None and honest["agreement"] is True


def test_the_singleton_can_be_scoped_and_reset(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_field_loop(**kwargs)` must never hand back the shared instance."""
    monkeypatch.setenv(field_mod.LESSON_DB_ENV, str(tmp_path / "shared.db"))
    field_mod.reset_field_loop()

    shared = field_mod.get_field_loop()
    scoped = field_mod.get_field_loop(lesson_db=tmp_path / "scoped.db",
                                      genome=GENOME.GenomeV2())

    assert shared is not scoped
    assert field_mod.get_field_loop() is shared

    field_mod.reset_field_loop()
    assert field_mod.get_field_loop() is not shared


def test_the_lesson_database_sits_beside_the_training_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default layout: one run, one data dir — no global state."""
    monkeypatch.delenv(field_mod.LESSON_DB_ENV, raising=False)

    assert field_mod.default_lesson_db_path(tmp_path / "training.db") == \
        tmp_path / "lessons.db"

    monkeypatch.setenv(field_mod.LESSON_DB_ENV, str(tmp_path / "explicit.db"))
    assert field_mod.default_lesson_db_path(tmp_path / "training.db") == \
        tmp_path / "explicit.db"


# ── 7. handles are handed back ───────────────────────────────────────────
def test_closing_the_loop_releases_its_lesson_database(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop owns one connection for life — dropping it must close it."""
    import sqlite3

    opened: List[Any] = []
    real_connect = sqlite3.connect

    def _spy(*args: Any, **kwargs: Any) -> Any:
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _spy)
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())
    loop.absorb(_run("coder"))

    assert opened, "the loop must have opened its lesson database"
    loop.close()

    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    loop.close()                       # idempotent
    assert loop.stats()["database"] is None
    assert loop.absorb(_run("coder", run_id="tr_after")) is not None  # memory only

# ── 8. the defensive branches of the loop ────────────────────────────────
class _NoAdviceGenome:
    """A genome that ranks fine but cannot advise (a half-broken adapter)."""

    def __init__(self) -> None:
        self._inner = GENOME.GenomeV2()

    def observe(self, agent_id: str, claimed: bool, truth: bool) -> None:
        self._genome().observe(agent_id, claimed, truth)

    def _real(self) -> Any:
        return GENOME.GenomeV2()

    def rank(self, include_retired: bool = True) -> List[Dict[str, Any]]:
        return [{"agent_id": "coder", "fitness": 0.6, "status": "stable"}]

    def advise(self, agent_id: str) -> Dict[str, Any]:
        raise RuntimeError("advice table is unreadable")

    def stats(self) -> Dict[str, Any]:
        return {"agents": 1}


def test_a_genome_whose_advise_explodes_still_lists_the_agent(
    tmp_path: Path,
) -> None:
    """A dashboard row is more useful than a traceback: advice degrades to empty."""
    loop = _loop(tmp_path, genome=_FakeAdviceGenome())

    rows = loop.fitness()

    assert [r["agent_id"] for r in rows] == ["coder"]
    assert rows[0]["action"] == ""
    assert rows[0]["reason"] == ""
    assert rows[0]["fitness"] == 0.5


def test_the_loop_evolve_survives_a_genome_without_advice(tmp_path: Path) -> None:
    loop = _loop(tmp_path, genome=_FakeAdviceGenome())

    actions = loop.evolve()

    assert [a["agent_id"] for a in actions] == ["coder"]
    assert actions[0]["mutated"] is False


def test_genome_stats_of_no_genome_is_none(tmp_path: Path) -> None:
    """``None`` (no genome) is distinct from ``{}`` (a genome that failed)."""
    loop = _loop(tmp_path, genome=None)

    assert loop._genome_stats(None) is None
    assert loop._genome_stats(_ExplodingStats()) == {}


class _ExplodingStats:
    def stats(self) -> Any:
        raise RuntimeError("stats exploded")


def test_a_genome_import_that_explodes_is_treated_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-ImportError while loading the genome must not crash the loop."""
    import importlib

    real = importlib.import_module

    def _fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith("genome_v2"):
            raise RuntimeError("genome package is half-installed")
        return real(name, *args, **kwargs)

    loop = _loop(tmp_path, genome=None)
    monkeypatch.setattr(importlib, "import_module", _fake)

    assert loop._genome_obj() is None


def test_absorbing_without_the_learning_layer_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop must run (and report) even with no lesson store available."""
    loop = _loop(tmp_path, genome=GENOME.GenomeV2())
    real = field_mod._learning

    def _no_store(name: str) -> Any:
        # The lesson itself distils fine; only the store layer is missing.
        return None if name == "lesson_store" else real(name)

    monkeypatch.setattr(field_mod, "_learning", _no_store)

    assert loop.absorb(_run("coder")) is None
    assert loop.stats()["lessons"] == 0


def test_closing_a_loop_whose_database_refuses_to_close_is_safe(
    tmp_path: Path,
) -> None:
    class _Stubborn:
        def close(self) -> None:
            raise RuntimeError("handle is already gone")

    loop = _loop(tmp_path, genome=GENOME.GenomeV2())
    loop._database = _Stubborn()

    loop.close()                      # must not raise

    assert loop.stats()["database"] is None

def test_evolve_skips_a_genome_row_without_an_agent_id(tmp_path: Path) -> None:
    """A junk row must be skipped, never crash the pass ``tick`` shares."""

    class _JunkRows:
        def rank(self, **kwargs: Any) -> List[Dict[str, Any]]:
            return [{}, {"agent_id": ""}, {"agent_id": "coder", "fitness": 0.6}]

        def advise(self, agent_id: str) -> Dict[str, Any]:
            return {"action": "keep", "reason": "stable", "fitness": 0.6}

        def stats(self) -> Dict[str, Any]:
            return {"agents": 1}

    loop = _loop(tmp_path, genome=_JunkRows())

    actions = loop.evolve()

    assert [a["agent_id"] for a in actions] == ["coder"]
    assert loop.fitness()[0]["fitness"] == 0.6

def test_a_persisted_lesson_is_skipped_when_its_store_cannot_be_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive contract: restoring is best-effort per lesson, never all-or-nothing.

    Both the DB opener and the store factory gate on the same import, so in
    production this guard cannot fire — it exists so a future store factory that
    refuses (a broken module, a locked handle) degrades to *fewer lessons* rather
    than a dead loop.  The seam is faked here on purpose.
    """
    source = _loop(tmp_path, genome=GENOME.GenomeV2())
    source.absorb(_run("coder"))
    db_path = source._lesson_db_path
    source.close()

    monkeypatch.setattr(field_mod.FieldLoop, "_store_for", lambda self, i: None)
    reopened = field_mod.FieldLoop(genome=GENOME.GenomeV2(), lesson_db=db_path)

    assert reopened._database is not None      # the DB still opened
    assert reopened.stats()["lessons"] == 0    # but no lesson could be restored
    reopened.close()
