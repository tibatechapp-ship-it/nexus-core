"""Hardening suite for the training *engine* and *store* (P3).

The pipeline is attacked the way production does, not the way a demo does:

* **invariants over a grid** — every graduation/certification decision is
  re-derived from the recorded run, so a silent math regression cannot pass;
* **exact gate arithmetic** — asserted against a *pinned* curriculum, which
  makes the numbers environment-independent instead of "whatever the plan
  happens to hold";
* **hostile input** — SQL, path traversal, unicode, empty, huge, ``NaN``/``inf``;
* **corruption** — a damaged row must degrade, never break the run listing;
* **durability** — a new store on the same file sees the same history;
* **concurrency** — parallel runs through WAL must not lose an update;
* **performance** — generous floors that only catch a real regression.

Everything is hermetic: a throwaway DB under ``tmp_path`` and
``field_loop=False`` unless a test says otherwise.  Stdlib-only, so the phone
gate runs every one of them.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from novamind.training import (
    GRADUATION_MIN_SCORE,
    TrainingEngine,
    TrainingRun,
    TrainingStore,
)
from novamind.training.engine import (
    CRITICAL_FAILURE_BELOW,
    DEFAULT_MODULE_MIN_SCORE,
    ModuleSpec,
    deterministic_evaluator,
    normalize_tag,
)
from novamind.training.store import SCHEMA_VERSION, default_db_path

#: Trainer qualities across every interesting boundary (below / at / above the
#: module floor and the graduation floor).
QUALITY_GRID = tuple(round(i / 10, 1) for i in range(11))

#: Agents with different curricula, so the grid is not one agent's accident.
GRID_AGENTS = ("coder", "planner", "analyst")


# ── helpers ──────────────────────────────────────────────────────────────
def _engine(path: Path, **kwargs: Any) -> TrainingEngine:
    """A hermetic engine on a throwaway DB (no genome side-effects)."""
    kwargs.setdefault("field_loop", False)
    return TrainingEngine(store=TrainingStore(path / "training.db"), **kwargs)


def _spec(name: str, hours: float = 1.0,
          min_score: float = DEFAULT_MODULE_MIN_SCORE) -> ModuleSpec:
    return ModuleSpec(name=name, hours=hours, min_score=min_score)


def _fix_curriculum(monkeypatch: pytest.MonkeyPatch, engine: TrainingEngine,
                    *specs: ModuleSpec) -> None:
    """Pin an engine's curriculum so the gate math is exactly predictable."""
    modules = tuple(specs)
    monkeypatch.setattr(engine, "modules_for", lambda *a, **k: modules)


def _mapping(values: Dict[str, float]) -> Any:
    """Evaluator reading a per-skill table (unknown skills score high)."""
    def evaluator(agent_id: str, skill: str, index: int, *,
                  quality: float = 0.85, salt: str = "") -> float:
        return values.get(skill, 0.9)
    return evaluator


def _flat(value: float) -> Any:
    """Evaluator returning the same score for every module."""
    def evaluator(agent_id: str, skill: str, index: int, *,
                  quality: float = 0.85, salt: str = "") -> float:
        return value
    return evaluator


def _recompute(run: TrainingRun) -> Dict[str, float]:
    """Independently re-derive the gate numbers from the recorded phases."""
    phases = [dict(p) for p in run.phases]
    total_hours = sum(float(p["hours"]) for p in phases) or 1.0
    passed = [p for p in phases if p["passed"]]
    completion = round(len(passed) / len(phases), 4) if phases else 0.0
    training = round(
        sum(float(p["score"]) * float(p["hours"]) for p in phases) / total_hours, 4
    ) if phases else 0.0
    gate = round(min(0.5 * completion + 0.5 * training, training), 4) \
        if phases else 0.0
    return {
        "completion_rate": completion,
        "training_score": training,
        "gate_score": gate,
        "final_score": round(0.5 * training + 0.5 * gate, 4) if phases else 0.0,
    }


def _cert_for(store: TrainingStore, run_id: str) -> Optional[Dict[str, Any]]:
    for cert in store.list_certificates(limit=500):
        if cert["run_id"] == run_id:
            return cert
    return None


def _run_id_of(runs: List[TrainingRun], agent_id: str) -> str:
    return next(r.run_id for r in runs if r.agent_id == agent_id)


def _a_run(*, run_id: str = "tr_x", agent_id: str = "coder",
           certified: bool = True, score: float = 0.9) -> TrainingRun:
    return TrainingRun(
        run_id=run_id, agent_id=agent_id, spec="default",
        started_at=1.0, finished_at=2.0,
        completion_rate=1.0 if certified else 0.0,
        training_score=score, gate_score=score, final_score=score,
        verdict="graduated" if certified else "failed", certified=certified,
        phases=(), detail={},
    )


# ── 1. gate invariants over a grid (the core safety property) ────────────
@pytest.mark.parametrize("agent_id", GRID_AGENTS)
def test_graduation_invariants_hold_across_the_quality_grid(
    tmp_path: Path, agent_id: str
) -> None:
    """No quality may certify an unqualified run — and no other way round.

    Every recorded run is re-derived from its own phases, so this fails if the
    score math, the completion floor and the certificate gate drift apart.
    """
    engine = _engine(tmp_path)
    certified_expected = 0

    for quality in QUALITY_GRID:
        run = engine.train(agent_id, quality=quality, salt="grid")

        for field, expected in _recompute(run).items():
            assert getattr(run, field) == expected, quality
        assert 0.0 <= run.training_score <= 1.0
        assert math.isfinite(run.final_score)
        for phase in run.phases:
            assert 0.0 <= phase["score"] <= 1.0
            assert phase["passed"] == (phase["score"] >= phase["min_score"])
            assert phase["critical"] == (phase["score"] < CRITICAL_FAILURE_BELOW)

        if run.certified:
            certified_expected += 1
            assert run.completion_rate >= 0.8
            assert run.training_score >= GRADUATION_MIN_SCORE
            assert run.final_score >= GRADUATION_MIN_SCORE
            assert not any(p["critical"] for p in run.phases)
            assert run.verdict == "graduated"
            cert = _cert_for(engine.store, run.run_id)
            assert cert is not None
            assert cert["score"] == run.final_score
            assert cert["agent_id"] == run.agent_id
        else:
            assert run.verdict in {"needs_retraining", "failed"}
            assert _cert_for(engine.store, run.run_id) is None

    stats = engine.store.stats()
    assert stats["runs"] == len(QUALITY_GRID)
    assert stats["certified"] == certified_expected
    assert stats["certificates"] == certified_expected


def test_the_quality_grid_certifies_somebody(tmp_path: Path) -> None:
    """A guard on the guard: the grid must exercise the certified branch."""
    engine = _engine(tmp_path)
    engine.evaluator = _flat(0.95)
    assert engine.train("coder").certified is True


@pytest.mark.parametrize("quality", QUALITY_GRID)
def test_the_floor_is_exact_on_a_pinned_curriculum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quality: float
) -> None:
    """Below the published floor ⇒ no certificate, at every tested quality."""
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("only"))
    engine.evaluator = _flat(quality)

    run = engine.train("coder")

    assert run.phases[0]["score"] == round(quality, 4)
    if quality >= GRADUATION_MIN_SCORE:
        assert run.certified is True
        assert _cert_for(engine.store, run.run_id) is not None
    else:
        assert run.certified is False
        assert _cert_for(engine.store, run.run_id) is None
        assert engine.store.stats()["certificates"] == 0


def test_the_graduation_floor_cannot_be_lowered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller asking for a lower bar is silently held to the published one."""
    engine = _engine(tmp_path, min_score=0.0)
    assert engine.min_score == GRADUATION_MIN_SCORE

    _fix_curriculum(monkeypatch, engine, _spec("only", min_score=0.5))
    engine.evaluator = _flat(GRADUATION_MIN_SCORE - 0.01)
    run = engine.train("coder")

    assert run.training_score < GRADUATION_MIN_SCORE
    assert run.certified is False


def test_the_graduation_floor_can_be_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path, min_score=0.9)
    assert engine.min_score == 0.9
    _fix_curriculum(monkeypatch, engine, _spec("only"))
    engine.evaluator = _flat(0.85)

    assert engine.train("coder").certified is False


# ── 2. exact gate arithmetic on a pinned curriculum ──────────────────────
def test_gate_arithmetic_is_exact(tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Hours-weighting, the clamp to the work quality, and the verdict."""
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("strong"), _spec("weak", hours=3.0))
    engine.evaluator = _mapping({"strong": 0.9, "weak": 0.5})

    run = engine.train("coder")

    # (0.9*1 + 0.5*3) / 4 = 0.6 ; the weak module (0.5 < 0.7) is not "passed".
    assert run.training_score == 0.6
    assert run.completion_rate == 0.5
    assert run.gate_score == 0.55          # min(0.5*0.5 + 0.5*0.6, 0.6)
    assert run.final_score == 0.575        # 0.5*0.6 + 0.5*0.55
    # 0.5 is *at* the critical floor, not below it — so this is not a failure.
    assert [p["critical"] for p in run.phases] == [False, False]
    assert run.certified is False
    assert run.verdict == "needs_retraining"
    assert run.duration >= 0.0
    assert run.detail["modules_total"] == 2
    assert run.detail["modules_passed"] == 1


def test_a_clean_curriculum_certifies_and_records_the_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("a"), _spec("b"))
    engine.evaluator = _mapping({"a": 0.9, "b": 0.8})

    run = engine.train("coder")

    assert run.training_score == 0.85
    assert run.completion_rate == 1.0
    assert run.gate_score == 0.85          # min(0.925, 0.85)
    assert run.final_score == 0.85
    assert run.certified is True
    assert run.verdict == "graduated"
    cert = _cert_for(engine.store, run.run_id)
    assert cert is not None
    assert cert["score"] == 0.85
    assert cert["payload"]["score"] == 0.85
    assert cert["payload"]["agent_id"] == "coder"
    assert cert["payload"]["certificate_id"] == cert["certificate_id"]


def test_a_critical_module_blocks_graduation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("a"), _spec("b"))
    engine.evaluator = _mapping({"a": 0.95, "b": CRITICAL_FAILURE_BELOW - 0.1})

    run = engine.train("coder")

    assert run.detail["critical_failures"] == ["b"]
    assert run.certified is False
    assert run.verdict == "failed"
    assert _cert_for(engine.store, run.run_id) is None


def test_an_incomplete_curriculum_needs_retraining_not_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completion below the floor without a critical module is a retrain."""
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, *(_spec(f"m{i}") for i in range(5)))
    engine.evaluator = _mapping({f"m{i}": (0.9 if i < 3 else 0.6)
                                for i in range(5)})

    run = engine.train("coder")

    assert run.completion_rate == 0.6
    assert run.detail["critical_failures"] == []
    assert run.certified is False
    assert run.verdict == "needs_retraining"


def test_an_empty_curriculum_is_handled(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """No modules must not divide by zero nor certify a 'good' empty run."""
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine)

    run = engine.train("coder")

    assert run.phases == ()
    assert (run.training_score, run.gate_score, run.final_score) == (0.0, 0.0, 0.0)
    assert run.completion_rate == 0.0
    assert run.certified is False
    # Below RETRAIN_FLOOR (0.5) an empty run is a hard failure, not a soft
    # "train me again" — the honest reading of zero evidence.
    assert run.verdict == "failed"


def test_curriculum_includes_the_agents_manifest_skills(tmp_path: Path) -> None:
    """The plan plus the agent's own declared skills — never an empty list."""
    engine = _engine(tmp_path)
    modules = engine.modules_for("coder")
    assert modules, "an agent must always resolve a curriculum"
    assert all(isinstance(m, ModuleSpec) for m in modules)
    assert len({m.name for m in modules}) == len(modules)
    assert engine.modules_for("coder", "coder")
    assert engine.modules_for("no-such-agent-at-all")


def test_normalize_tag_flattens_manifest_tags() -> None:
    assert normalize_tag("Code Review") == "code_review"
    assert normalize_tag("  bug-fixing!  ") == "bug_fixing"
    assert normalize_tag("A/B Testing") == "a_b_testing"
    assert normalize_tag("") == ""
    assert normalize_tag("__x__") == "x"


# ── 3. the deterministic evaluator ───────────────────────────────────────
def test_the_evaluator_is_deterministic_and_salt_sensitive() -> None:
    first = [deterministic_evaluator("coder", f"s{i}", i) for i in range(20)]
    again = [deterministic_evaluator("coder", f"s{i}", i) for i in range(20)]
    salted = [deterministic_evaluator("coder", f"s{i}", i, salt="x")
              for i in range(20)]

    assert first == again
    assert first != salted
    assert all(0.0 <= s <= 1.0 for s in first)


def test_the_evaluator_tracks_the_requested_quality() -> None:
    assert deterministic_evaluator("coder", "m", 0, quality=0.8) > \
        deterministic_evaluator("coder", "m", 0, quality=0.2)


def test_a_rerun_reproduces_the_curriculum_scores(tmp_path: Path) -> None:
    """Same agent + same salt ⇒ identical scores (the whole point of P3)."""
    engine = _engine(tmp_path)
    first = engine.train("coder", salt="repeat")
    second = engine.train("coder", salt="repeat")

    assert [(p["skill"], p["score"]) for p in first.phases] == \
           [(p["skill"], p["score"]) for p in second.phases]
    assert first.training_score == second.training_score
    assert first.certified == second.certified
    assert first.run_id != second.run_id


def test_a_different_salt_changes_the_scores(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.train("coder", salt="")
    second = engine.train("coder", salt="alt-salt")

    assert [(p["skill"], p["score"]) for p in first.phases] != \
           [(p["skill"], p["score"]) for p in second.phases]


# ── 4. evaluator contract + hostile evaluator output ────────────────────
def test_the_evaluator_call_contract_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("alpha"), _spec("beta"))
    calls: List[Any] = []

    def evaluator(agent_id: str, skill: str, index: int, *,
                  quality: float, salt: str) -> float:
        calls.append((agent_id, skill, index, quality, salt))
        return 0.9

    engine.evaluator = evaluator
    engine.train("coder", quality=0.42, salt="tz")

    assert calls == [
        ("coder", "alpha", 0, 0.42, "tz"),
        ("coder", "beta", 1, 0.42, "tz"),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(5.0, 1.0), (-3.0, 0.0), (float("inf"), 1.0), (float("-inf"), 0.0)],
)
def test_the_engine_clamps_a_hostile_evaluator_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: float, expected: float
) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("m"))
    engine.evaluator = _flat(raw)

    run = engine.train("coder")

    assert run.phases[0]["score"] == expected
    assert math.isfinite(run.training_score)
    assert 0.0 <= run.training_score <= 1.0


def test_a_nan_evaluator_cannot_poison_the_average(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("m"), _spec("n"))
    engine.evaluator = _flat(float("nan"))

    run = engine.train("coder")

    assert all(math.isfinite(p["score"]) for p in run.phases)
    assert math.isfinite(run.training_score)
    assert math.isfinite(engine.store.stats()["avg_score"])


def test_a_non_numeric_evaluator_fails_one_run_without_killing_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine, _spec("m"))

    def hostile(agent_id: str, skill: str, index: int, *,
                quality: float = 0.85, salt: str = "") -> float:
        return "not-a-number"  # type: ignore[return-value]

    engine.evaluator = hostile

    with pytest.raises((TypeError, ValueError)):
        engine.train("coder")

    runs = engine.train_batch(["coder", "planner"])
    assert len(runs) == 2
    assert all(r.certified is False for r in runs)
    assert all(r.verdict == "failed" for r in runs)
    assert all("error" in r.detail for r in runs)


# ── 4b. hostile input: injection, traversal, unicode ────────────────────
HOSTILE_IDS = (
    "'; DROP TABLE training_runs;--",
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "\x00null-byte",
    "🧠💥 unicode 'agent' \"quoted\"",
    "a" * 1000,
    "%s %d {0} $(whoami) `id`",
    "line\nbreak\ttab",
)


@pytest.mark.parametrize("agent_id", HOSTILE_IDS)
def test_hostile_agent_ids_round_trip_and_cannot_corrupt_the_store(
    tmp_path: Path, agent_id: str
) -> None:
    store = TrainingStore(tmp_path / "training.db")
    engine = TrainingEngine(store=store, field_loop=False)
    engine.evaluator = _flat(0.9)

    run = engine.train(agent_id, salt="evil")
    fetched = store.get_run(run.run_id)

    assert fetched is not None
    assert fetched.agent_id == agent_id           # verbatim, not sanitised away
    assert [dict(p) for p in fetched.phases] == [dict(p) for p in run.phases]
    assert [r.agent_id for r in store.list_runs(agent_id=agent_id)] == [agent_id]
    assert store.stats()["runs"] == 1              # the tables still exist
    assert len(store.list_runs(limit=1)) == 1


def test_a_hostile_agent_id_never_becomes_a_path(tmp_path: Path) -> None:
    """Agent ids are data: they must not steer the DB path."""
    store = TrainingStore(tmp_path / "training.db")
    engine = TrainingEngine(store=store, field_loop=False)
    engine.train("../../pwned", spec="../../pwned")

    assert not (tmp_path.parent / "pwned").exists()
    assert store.path == tmp_path / "training.db"


def test_a_unicode_payload_survives_json_serialisation(tmp_path: Path) -> None:
    store = TrainingStore(tmp_path / "training.db")
    run = TrainingRun(
        run_id="tr_unicode", agent_id="وڪيل", spec="التدريب",
        started_at=1.0, finished_at=2.0,
        completion_rate=1.0, training_score=0.9, gate_score=0.9,
        final_score=0.9, verdict="graduated", certified=True,
        phases=({"skill": "قراءة", "hours": 1.0, "min_score": 0.7,
                 "score": 0.9, "passed": True, "critical": False, "index": 0},),
        detail={"note": "to'be or \"not\" to be — 100% 🎯"},
    )
    store.save_run(run)
    back = store.get_run("tr_unicode")

    assert back is not None
    assert back.agent_id == "وڪيل"
    assert back.detail["note"] == "to'be or \"not\" to be — 100% 🎯"
    assert dict(back.phases[0]) == dict(run.phases[0])


# ── 5. corruption tolerance ─────────────────────────────────────────────
def _raw_exec(path: Path, sql: str, params: tuple[Any, ...]) -> None:
    with closing(sqlite3.connect(str(path))) as conn:
        conn.execute(sql, params)
        conn.commit()


def test_the_store_closes_every_connection_it_opens(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """No handle may outlive its operation (a phone has few file descriptors)."""
    created = []
    real_connect = sqlite3.connect

    def spy(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)
        created.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)

    store = TrainingStore(tmp_path / "training.db")
    run = _a_run()
    store.save_run(run)
    store.get_run(run.run_id)
    store.list_runs()
    store.stats()

    assert len(created) >= 4, "each operation must open its own connection"
    for conn in created:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_a_damaged_run_row_degrades_instead_of_breaking_the_listing(
    tmp_path: Path,
) -> None:
    """A corrupt JSON column must not 500 the run history."""
    engine = _engine(tmp_path)
    engine.evaluator = _flat(0.9)
    good = engine.train("coder")
    bad = engine.train("planner")

    _raw_exec(
        engine.store.path,
        "UPDATE training_runs SET phases=?, detail=? WHERE run_id=?",
        ("{not json", "also-not-json", bad.run_id),
    )

    runs = engine.store.list_runs(limit=50)

    assert len(runs) == 2
    damaged = next(r for r in runs if r.run_id == bad.run_id)
    assert damaged.phases == ()
    assert damaged.detail == {}
    assert damaged.agent_id == "planner"
    assert engine.store.get_run(bad.run_id) is not None
    assert engine.store.stats()["runs"] == 2
    # The healthy row survives the neighbour's damage, intact.
    intact = engine.store.get_run(good.run_id)
    assert intact is not None
    assert intact.phases and intact.detail
    assert intact.agent_id == "coder"
    assert engine.store.latest_run("coder") is not None


def test_a_damaged_certificate_payload_still_lists(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.evaluator = _flat(0.95)
    run = engine.train("coder")

    _raw_exec(
        engine.store.path,
        "UPDATE training_certificates SET payload=? WHERE run_id=?",
        ("{not json", run.run_id),
    )

    certs = engine.store.list_certificates()
    assert len(certs) == 1
    assert certs[0]["payload"] == {}
    assert certs[0]["score"] >= GRADUATION_MIN_SCORE


def test_the_schema_is_recorded_and_the_tables_exist(tmp_path: Path) -> None:
    store = TrainingStore(tmp_path / "training.db")
    with closing(sqlite3.connect(str(store.path))) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"training_runs", "training_certificates"} <= names


def test_a_bogus_database_path_fails_loudly_at_construction(tmp_path: Path) -> None:
    """A file where a directory belongs must raise, not silently lose runs."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")

    with pytest.raises((sqlite3.Error, OSError)):
        TrainingStore(blocker / "training.db")


# ── 6. durability ───────────────────────────────────────────────────────
def test_a_new_store_on_the_same_file_sees_the_whole_history(tmp_path: Path) -> None:
    path = tmp_path / "training.db"
    engine = TrainingEngine(store=TrainingStore(path), field_loop=False)
    engine.evaluator = _flat(0.9)
    trained = engine.train_batch(["coder", "planner", "analyst"], salt="persist")

    reopened = TrainingStore(path)
    runs = reopened.list_runs(limit=50)

    assert {r.run_id for r in runs} == {r.run_id for r in trained}
    assert reopened.stats()["runs"] == 3
    assert reopened.stats()["certificates"] == \
        sum(1 for r in trained if r.certified)
    for cert in reopened.list_certificates():
        assert cert["score"] >= GRADUATION_MIN_SCORE


def test_stats_agree_with_the_hand_computed_truth(tmp_path: Path) -> None:
    store = TrainingStore(tmp_path / "training.db")
    engine = TrainingEngine(store=store, field_loop=False)
    engine.evaluator = _flat(0.9)
    engine.train("coder")
    engine.train("planner")

    stats = store.stats()
    runs = store.list_runs(limit=50)

    assert stats["runs"] == len(runs) == 2
    assert stats["agents_trained"] == 2
    assert stats["certified"] == sum(1 for r in runs if r.certified)
    assert stats["certificates"] == len(store.list_certificates(limit=50))
    assert stats["certification_rate"] == round(stats["certified"] / 2, 4)
    assert stats["avg_score"] == round(
        sum(r.final_score for r in runs) / 2, 4
    )
    assert stats["schema_version"] == SCHEMA_VERSION
    assert stats["path"] == str(store.path)


def test_the_default_db_path_is_stable_and_overridable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUS_TRAINING_DB", raising=False)
    monkeypatch.delenv("NEXUS_DB", raising=False)
    assert default_db_path().name == "training.db"

    monkeypatch.setenv("NEXUS_TRAINING_DB", str(tmp_path / "explicit.db"))
    assert default_db_path() == tmp_path / "explicit.db"


def test_the_same_run_id_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    store = TrainingStore(tmp_path / "training.db")
    run = _a_run(run_id="tr_same")

    store.save_run(run)
    store.save_run(run)
    assert store.stats()["runs"] == 1

    store.issue_certificate(certificate_id="cert_a", run=run, signature="s")
    store.issue_certificate(certificate_id="cert_a", run=run, signature="s")
    assert store.stats()["certificates"] == 1


def test_a_certificate_id_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.evaluator = _flat(0.95)
    run = engine.train("coder")

    first = engine._issue_certificate(run)          # noqa: SLF001 - contract
    second = engine._issue_certificate(run)         # noqa: SLF001 - contract

    assert first["certificate_id"] == second["certificate_id"]
    assert engine.store.stats()["certificates"] == 1


def test_list_runs_respects_its_bounds(tmp_path: Path) -> None:
    store = TrainingStore(tmp_path / "training.db")
    for index in range(6):
        store.save_run(_a_run(run_id=f"tr_{index}", agent_id=f"a{index % 2}"))

    assert len(store.list_runs(limit=3)) == 3
    assert len(store.list_runs(limit=0)) == 1        # clamped up
    assert len(store.list_runs(limit=10_000)) == 6   # clamped down
    assert len(store.list_runs(agent_id="a0")) == 3
    assert store.latest_run("a0") is not None
    assert store.latest_run("nobody") is None


# ── 7. concurrency ──────────────────────────────────────────────────────
def test_parallel_runs_are_not_lost(tmp_path: Path) -> None:
    """WAL + a write lock: every concurrent run persisted exactly once."""
    engine = _engine(tmp_path)
    agents = [f"agent_{i % 4}" for i in range(24)]
    errors: List[BaseException] = []

    def work(agent_id: str) -> None:
        try:
            engine.train(agent_id, salt="conc")
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, agents))

    assert errors == []
    runs = engine.store.list_runs(limit=500)
    assert len(runs) == len(agents)
    assert engine.store.stats()["runs"] == len(agents)
    assert engine.store.stats()["certificates"] == sum(1 for r in runs if r.certified)


def test_reads_during_writes_never_raise(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    stop = threading.Event()
    failures: List[BaseException] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                engine.store.stats()
                engine.store.list_runs(limit=5)
                engine.store.list_certificates(limit=5)
            except BaseException as exc:  # noqa: BLE001 - reported below
                failures.append(exc)
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        for _ in range(15):
            engine.train("coder", salt="rw")
    finally:
        stop.set()
        thread.join(timeout=5)

    assert failures == []
    assert engine.store.stats()["runs"] == 15


# ── 8. performance ──────────────────────────────────────────────────────
def test_a_hundred_runs_stay_within_budget(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    started = time.monotonic()
    for _ in range(100):
        engine.train("coder", salt="perf")
    elapsed = time.monotonic() - started

    assert engine.store.stats()["runs"] == 100
    assert elapsed < 30.0, f"100 runs took {elapsed:.1f}s"


def test_a_large_curriculum_stays_linear(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(tmp_path)
    _fix_curriculum(monkeypatch, engine,
                    *(_spec(f"module_{i:03d}") for i in range(300)))
    started = time.monotonic()
    run = engine.train("coder")
    elapsed = time.monotonic() - started

    assert len(run.phases) == 300
    assert elapsed < 10.0, f"300 modules took {elapsed:.1f}s"


def test_the_engine_does_not_accumulate_history_in_process(tmp_path: Path) -> None:
    """The store owns history; the engine must not hold it in memory."""
    engine = _engine(tmp_path)
    for _ in range(30):
        engine.train("coder")

    assert len(engine.store.list_runs(limit=500)) == 30
    assert not [name for name in vars(engine) if "runs" in name]


def test_the_status_payload_shape_is_a_stable_contract(tmp_path: Path) -> None:
    """The dashboard reads these keys by name — changing them breaks the UI."""
    stats = TrainingStore(tmp_path / "training.db").stats()
    assert set(stats) >= {
        "runs", "certified", "agents_trained", "certificates",
        "avg_score", "certification_rate", "schema_version", "path",
    }
    assert stats["certification_rate"] == 0.0
    assert stats["avg_score"] == 0.0
    assert json.dumps(stats)          # JSON-safe for the HTTP layer
