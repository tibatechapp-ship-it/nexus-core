"""Training pipeline — pure layers (models, store, engine).

Hermetic: a temp SQLite file, an injected clock and an injected evaluator, so
nothing here touches the network, the real data dir or wall-clock luck.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from novamind.training import (
    CRITICAL_FAILURE_BELOW,
    DEFAULT_MODULE_MIN_SCORE,
    GRADUATION_MIN_SCORE,
    ModuleSpec,
    TrainingEngine,
    TrainingStore,
    TrainingVerdict,
    default_db_path,
    deterministic_evaluator,
    get_store,
    normalize_tag,
    reset_engine,
    reset_signer,
    reset_store,
    verdict_for,
)
from novamind.training.engine import TrainingRun


# ── fixtures ─────────────────────────────────────────────────────────────
@pytest.fixture()
def store(tmp_path: Path) -> TrainingStore:
    """A store backed by a throwaway database."""
    return TrainingStore(tmp_path / "training.db")


@pytest.fixture()
def engine(store: TrainingStore) -> TrainingEngine:
    """An engine with no genome side-effects and a frozen clock."""
    ticks = iter(range(0, 10_000))
    return TrainingEngine(
        store=store, clock=lambda: float(next(ticks)), feed_genome=False
    )


def _flat(score: float):
    """An evaluator that returns ``score`` for every module."""

    def evaluator(agent_id, skill, index, *, quality=0.85, salt=""):
        return score

    return evaluator


# ── models ───────────────────────────────────────────────────────────────
def test_graduation_floor_is_the_published_constant() -> None:
    assert GRADUATION_MIN_SCORE == 0.75


@pytest.mark.parametrize(
    ("graduated", "score", "expected"),
    [
        (True, 0.80, TrainingVerdict.GRADUATED.value),
        (False, 0.75, TrainingVerdict.NEEDS_RETRAINING.value),
        (False, 0.50, TrainingVerdict.NEEDS_RETRAINING.value),
        (False, 0.4999, TrainingVerdict.FAILED.value),
    ],
)
def test_verdict_for_maps_score_bands(graduated, score, expected) -> None:
    assert verdict_for(graduated, score) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"critical": True}, TrainingVerdict.FAILED.value),
        ({"completion_rate": 0.4}, TrainingVerdict.FAILED.value),
        ({"completion_rate": 1.0}, TrainingVerdict.NEEDS_RETRAINING.value),
    ],
)
def test_verdict_for_prefers_evidence_over_the_raw_score(
    overrides, expected
) -> None:
    assert verdict_for(False, 0.72, **overrides) == expected


def test_training_run_duration_and_dict() -> None:
    run = TrainingRun(
        run_id="tr_x", agent_id="coder", spec="coder",
        started_at=100.0, finished_at=100.5,
        completion_rate=1.0, training_score=0.9, gate_score=0.9,
        final_score=0.9, verdict="graduated", certified=True,
        phases=({"skill": "a", "score": 0.9},), detail={"k": "v"},
    )
    assert run.duration == 0.5
    payload = run.to_dict()
    assert payload["run_id"] == "tr_x"
    assert payload["phases"] == [{"skill": "a", "score": 0.9}]
    assert payload["detail"] == {"k": "v"}
    assert payload["certified"] is True


# ── store ────────────────────────────────────────────────────────────────
def test_store_roundtrip_and_aggregates(store: TrainingStore, engine) -> None:
    run = engine.train("coder")
    assert store.get_run(run.run_id) is not None
    assert store.latest_run("coder").run_id == run.run_id
    assert store.latest_run("nobody") is None
    assert [r.run_id for r in store.list_runs(agent_id="coder")] == [run.run_id]

    stats = store.stats()
    assert stats["runs"] == 1
    assert stats["agents_trained"] == 1
    assert stats["certified"] == 1
    assert stats["certificates"] == 1
    assert stats["certification_rate"] == 1.0
    assert stats["path"].endswith("training.db")


def test_store_persists_across_instances(tmp_path: Path, engine) -> None:
    engine.train("coder")
    reopened = TrainingStore(tmp_path / "training.db")
    assert reopened.stats()["runs"] == 1
    version = sqlite3.connect(str(tmp_path / "training.db")).execute(
        "PRAGMA user_version"
    ).fetchone()[0]
    assert version == 1


def test_store_certificates_can_be_filtered(store: TrainingStore) -> None:
    assert store.list_certificates() == []
    assert store.list_certificates(agent_id="ghost") == []


def test_store_list_runs_clamps_limit(store: TrainingStore, engine) -> None:
    engine.train("coder")
    assert len(store.list_runs(limit=0)) == 1
    assert len(store.list_runs(limit=9999)) == 1


def test_default_db_path_honours_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_TRAINING_DB", str(tmp_path / "explicit.db"))
    assert default_db_path() == tmp_path / "explicit.db"

    monkeypatch.delenv("NEXUS_TRAINING_DB")
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "sessions.db"))
    assert default_db_path() == tmp_path / "training.db"


def test_get_store_singleton_and_reset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_TRAINING_DB", str(tmp_path / "s.db"))
    reset_store()
    first = get_store()
    assert get_store() is first
    reset_store()
    assert get_store() is not first
    # An explicit path always builds a fresh, independent store.
    assert get_store(tmp_path / "other.db").path != first.path
    reset_store()


# ── engine: curriculum ───────────────────────────────────────────────────
def test_curriculum_is_plan_plus_manifest_tags(engine) -> None:
    modules = engine.modules_for("coder")
    names = [m.name for m in modules]
    # The universal curriculum and the coder specialisation both survive.
    assert "understand_nova_philosophy" in names
    assert "python_mastery" in names
    # The agent's own manifest tags are appended exactly once.
    assert len(names) == len(set(names))
    sources = {m.source for m in modules}
    assert sources <= {"plan", "manifest"}
    assert all(m.min_score > 0 for m in modules)


def test_plan_reports_module_count_and_last_run(engine) -> None:
    before = engine.plan("coder")
    assert before["latest_run"] is None
    assert before["module_count"] == len(before["modules"])
    assert before["min_score"] == GRADUATION_MIN_SCORE
    assert before["critical_failure_below"] == CRITICAL_FAILURE_BELOW

    engine.train("coder")
    after = engine.plan("coder")
    assert after["latest_run"]["agent_id"] == "coder"


def test_explicit_spec_overrides_the_manifest(engine) -> None:
    assert engine.plan("coder", spec="security")["spec"] == "security"
    modules = [m.name for m in engine.modules_for("coder", spec="security")]
    assert "owasp_top10" in modules


def test_normalize_tag_folds_manifest_naming() -> None:
    assert normalize_tag("code-review") == "code_review"
    assert normalize_tag("  Security  Audit ") == "security_audit"


def test_module_spec_to_dict() -> None:
    assert ModuleSpec(name="a").to_dict() == {
        "name": "a", "hours": 1.0,
        "min_score": DEFAULT_MODULE_MIN_SCORE, "source": "plan",
    }


# ── engine: determinism ──────────────────────────────────────────────────
def test_evaluator_is_deterministic_and_bounded() -> None:
    args = ("coder", "python_mastery", 3)
    first = deterministic_evaluator(*args, salt="s")
    assert first == deterministic_evaluator(*args, salt="s")
    assert first != deterministic_evaluator(*args, salt="other")
    assert 0.0 <= first <= 1.0
    assert deterministic_evaluator(*args, quality=1.0) <= 1.0
    assert deterministic_evaluator(*args, quality=0.0) >= 0.0


def test_two_runs_of_one_agent_agree(engine) -> None:
    first = engine.train("coder")
    second = engine.train("coder")
    assert [p["score"] for p in first.phases] == [p["score"] for p in second.phases]
    assert first.final_score == second.final_score


# ── engine: graduation gate ──────────────────────────────────────────────
def test_strong_run_graduates_and_is_certified(store: TrainingStore, engine) -> None:
    run = engine.train("coder", quality=0.95)
    assert run.verdict == TrainingVerdict.GRADUATED.value
    assert run.certified is True
    assert run.completion_rate >= 0.8
    certs = store.list_certificates(agent_id="coder")
    assert len(certs) == 1
    assert certs[0]["run_id"] == run.run_id
    assert certs[0]["score"] == run.final_score


def test_no_certificate_below_the_floor(store: TrainingStore, engine) -> None:
    """The stated negative: a mediocre run must not earn a certificate."""
    engine.evaluator = _flat(0.72)
    run = engine.train("coder")
    assert run.certified is False
    assert run.final_score < GRADUATION_MIN_SCORE
    # Everything passed its own module floor, but the work was not good enough.
    assert run.completion_rate >= 0.8
    assert run.verdict == TrainingVerdict.NEEDS_RETRAINING.value
    assert store.list_certificates(agent_id="coder") == []


def test_below_every_module_floor_fails_hard(store: TrainingStore, engine) -> None:
    engine.evaluator = _flat(0.60)
    run = engine.train("coder")
    assert run.certified is False
    assert run.completion_rate == 0.0
    assert run.verdict == TrainingVerdict.FAILED.value
    assert store.list_certificates(agent_id="coder") == []


def test_weak_run_fails_hard(store: TrainingStore, engine) -> None:
    engine.evaluator = _flat(0.30)
    run = engine.train("coder")
    assert run.verdict == TrainingVerdict.FAILED.value
    assert run.certified is False
    assert run.detail["critical_failures"]
    assert store.list_certificates(agent_id="coder") == []


def test_critical_failure_blocks_graduation_even_when_average_is_high(engine) -> None:
    """One disastrous module blocks graduation despite a strong average."""
    def evaluator(agent_id, skill, index, *, quality=0.85, salt=""):
        return 0.2 if skill == "python_mastery" else 0.98

    engine.evaluator = evaluator
    run = engine.train("coder")
    assert run.training_score > GRADUATION_MIN_SCORE
    assert "python_mastery" in run.detail["critical_failures"]
    assert run.certified is False


def test_partial_completion_blocks_graduation(engine) -> None:
    """Completing fewer than 80% of modules is not graduation."""
    engine.evaluator = lambda *a, **k: 0.80 if a[2] < 4 else 0.60
    run = engine.train("coder")
    assert run.completion_rate < 0.8
    assert run.certified is False


def test_floor_cannot_be_lowered(tmp_path: Path) -> None:
    cheap = TrainingEngine(
        store=TrainingStore(tmp_path / "t.db"), min_score=0.1, feed_genome=False
    )
    assert cheap.min_score == GRADUATION_MIN_SCORE


def test_floor_can_be_raised(tmp_path: Path) -> None:
    strict = TrainingEngine(store=TrainingStore(tmp_path / "t.db"), min_score=0.95)
    assert strict.min_score == 0.95


# ── engine: batch + errors ───────────────────────────────────────────────
def test_train_batch_trains_every_agent(engine) -> None:
    runs = engine.train_batch(["coder", "tester"])
    assert [r.agent_id for r in runs] == ["coder", "tester"]
    assert all(r.run_id for r in runs)


def test_train_batch_isolates_a_failing_agent(engine) -> None:
    def evaluator(agent_id, skill, index, *, quality=0.85, salt=""):
        if agent_id == "tester":
            raise RuntimeError("boom")
        return 0.95

    engine.evaluator = evaluator
    runs = engine.train_batch(["coder", "tester"])
    assert len(runs) == 2
    assert runs[0].certified is True
    assert runs[1].verdict == "failed"
    assert runs[1].detail["error"] == "boom"
    assert runs[1].run_id.startswith("tr_err_")


def test_engine_uses_the_singleton_store_when_none_given(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_TRAINING_DB", str(tmp_path / "s.db"))
    reset_store()
    assert TrainingEngine().store is get_store()
    reset_store()


def test_singleton_engine_and_reset() -> None:
    reset_engine()
    from novamind.training import get_engine

    assert get_engine() is get_engine()
    reset_engine()
    # Passing kwargs always returns a fresh, unshared engine.
    assert get_engine(feed_genome=False) is not get_engine(feed_genome=False)
    reset_engine()


# ── certificate signing (optional dependency) ────────────────────────────
def test_certificate_is_signed_or_explicitly_unsigned(
    store: TrainingStore, engine
) -> None:
    reset_signer()
    try:
        engine.train("coder", quality=0.95)
        cert = store.list_certificates(agent_id="coder")[0]
        # Either a real signature or an empty string — never a fabricated one.
        assert isinstance(cert["signature"], str)
        if cert["signature"]:
            assert len(cert["signature"]) > 16
    finally:
        reset_signer()


def test_fingerprint_of_certificate_id(store: TrainingStore, engine) -> None:
    engine.train("coder", quality=0.95)
    cert = store.list_certificates(agent_id="coder")[0]
    assert cert["certificate_id"].startswith("cert_")
    assert len(cert["certificate_id"]) == len("cert_") + 16


def test_certificate_payload_is_self_consistent(store: TrainingStore, engine) -> None:
    run = engine.train("coder", quality=0.95)
    cert = store.list_certificates(agent_id="coder")[0]
    assert cert["payload"]["certificate_id"] == cert["certificate_id"]
    assert cert["payload"]["agent_id"] == run.agent_id
    assert cert["payload"]["score"] == run.final_score
