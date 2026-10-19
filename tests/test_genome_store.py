"""Tests for the genome persistence layer (src/novamind/genome_store.py).

Covers the file-path resolution order, tolerant load, atomic save, the
seed-and-adopt ``install`` path (identity preserved for the shared singleton),
and the opt-in persistence hook wired into :class:`GenomeV2`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.novamind import genome_store
from src.novamind.genome_v2 import (
    NEUTRAL_FITNESS,
    GenomeV2,
    get_genome_v2,
    reset_genome_v2,
    set_persistence_hook,
)


@pytest.fixture(autouse=True)
def _restore_globals():
    """Every test leaves the process-wide genome and hook as it found them."""
    yield
    reset_genome_v2()
    set_persistence_hook(None)


def _row(genome: GenomeV2, agent_id: str) -> dict:
    """``snapshot`` is Optional by contract — fail loudly here, not with a TypeError."""
    row = genome.snapshot(agent_id)
    assert row is not None
    return row


# ── default_path ─────────────────────────────────────────────────────────
def test_env_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "explicit.json"
    monkeypatch.setenv("NEXUS_GENOME_PATH", str(target))
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "other.db"))
    assert genome_store.default_path() == target


def test_sibling_of_training_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NEXUS_GENOME_PATH", raising=False)
    monkeypatch.setenv("NEXUS_TRAINING_DB", str(tmp_path / "training.db"))
    monkeypatch.delenv("NEXUS_DB", raising=False)
    assert genome_store.default_path() == tmp_path / "genome.json"


def test_sibling_of_generic_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NEXUS_GENOME_PATH", raising=False)
    monkeypatch.delenv("NEXUS_TRAINING_DB", raising=False)
    monkeypatch.setenv("NEXUS_DB", str(tmp_path / "nexus.db"))
    assert genome_store.default_path() == tmp_path / "genome.json"


def test_repo_data_dir_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NEXUS_GENOME_PATH", "NEXUS_TRAINING_DB", "NEXUS_DB"):
        monkeypatch.delenv(name, raising=False)
    assert genome_store.default_path() == genome_store._repo_root() / "data" / "genome.json"


def test_repo_root_is_the_actual_checkout() -> None:
    """Regression: the module sits at ``<repo>/src/novamind/`` (parents[2]).

    An off-by-one here writes the genome *outside* the repo — a bug that still
    passed every test because they only compared against the helper itself.
    """
    repo = Path(__file__).resolve().parents[1]  # <repo>/tests/this_file.py
    assert genome_store._repo_root() == repo
    assert (repo / "pyproject.toml").is_file()


# ── load ─────────────────────────────────────────────────────────────────
def test_load_missing_file_is_an_empty_genome(tmp_path: Path) -> None:
    genome = genome_store.load(tmp_path / "nope.json")
    assert isinstance(genome, GenomeV2)
    assert genome.stats()["agents"] == 0


def test_load_round_trips_saved_state(tmp_path: Path) -> None:
    path = tmp_path / "genome.json"
    original = GenomeV2()
    original.observe_outcome("coder", True, duration=1.5, task="t")
    original.observe("analyst", "yes", "approve")
    assert genome_store.save(original, path) is True

    restored = genome_store.load(path)
    assert restored.to_dict()["agents"].keys() == original.to_dict()["agents"].keys()
    assert _row(restored, "coder")["task_observations"] == 1
    assert _row(restored, "analyst")["agreements"] == 1


@pytest.mark.parametrize("junk", ["{not json", "[]", "42", '"text"', "null"])
def test_load_tolerates_corrupt_or_wrong_shape(tmp_path: Path, junk: str) -> None:
    path = tmp_path / "genome.json"
    path.write_text(junk, encoding="utf-8")
    assert genome_store.load(path).stats()["agents"] == 0


def test_load_tolerates_a_damaged_agent_row(tmp_path: Path) -> None:
    path = tmp_path / "genome.json"
    path.write_text(json.dumps({"agents": {"coder": "not-a-mapping"}}), encoding="utf-8")
    assert genome_store.load(path).stats()["agents"] == 0


# ── save ─────────────────────────────────────────────────────────────────
def test_save_creates_parent_and_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "genome.json"
    assert genome_store.save(GenomeV2(), path) is True
    assert path.is_file()
    assert list(path.parent.glob(".genome-*")) == []  # temp file was consumed


def test_save_returns_false_when_unwritable(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    assert genome_store.save(GenomeV2(), blocker / "genome.json") is False


# ── adopt ────────────────────────────────────────────────────────────────
def test_adopt_keeps_identity_but_takes_state() -> None:
    shared = GenomeV2()
    assert shared.snapshot("coder") is None

    other = GenomeV2()
    other.observe_outcome("coder", True, task="x")
    other.observe("critic", "yes", "reject")

    returned = shared.adopt(other)
    assert returned is shared                      # identity preserved
    assert _row(shared, "coder")["task_observations"] == 1
    assert _row(shared, "critic")["dissent"] == 1
    assert shared.to_dict()["seq"] == other.to_dict()["seq"]


def test_adopt_none_resets_in_place() -> None:
    shared = GenomeV2()
    shared.observe_outcome("coder", True)
    shared.adopt(None)  # type: ignore[arg-type]
    assert shared.stats()["agents"] == 0
    assert shared.to_dict()["seq"] == 0


# ── persistence hook ─────────────────────────────────────────────────────
def test_hook_fires_on_every_mutator() -> None:
    seen: list[int] = []
    set_persistence_hook(lambda g: seen.append(g.stats()["agents"]))
    try:
        genome = GenomeV2()
        genome.observe("analyst", "yes", "approve")
        genome.observe_outcome("coder", True)
        genome.mutate("coder")
        genome.retire("coder")
        genome.revive("coder")
    finally:
        set_persistence_hook(None)
    assert len(seen) == 5


def test_hook_is_silent_when_unset() -> None:
    set_persistence_hook(None)
    genome = GenomeV2()
    # must not raise with no hook installed
    genome.observe_outcome("coder", True)
    assert _row(genome, "coder")["task_observations"] == 1


def test_a_broken_hook_never_breaks_the_caller() -> None:
    def boom(_: GenomeV2) -> None:
        raise RuntimeError("disk on fire")

    set_persistence_hook(boom)
    try:
        genome = GenomeV2()
        genome.observe_outcome("coder", True)          # must not raise
    finally:
        set_persistence_hook(None)
    assert _row(genome, "coder")["task_observations"] == 1


# ── install ──────────────────────────────────────────────────────────────
def test_install_seeds_roster_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "genome.json"
    genome = genome_store.install(["coder", "analyst", "", "  ", "coder"],
                                  path, genome=GenomeV2())
    assert set(genome.to_dict()["agents"]) == {"coder", "analyst"}
    assert _row(genome, "coder")["fitness"] == pytest.approx(NEUTRAL_FITNESS)
    assert path.is_file()


def test_install_adopts_saved_state_in_place(tmp_path: Path) -> None:
    path = tmp_path / "genome.json"
    saved = GenomeV2()
    saved.observe_outcome("coder", True, quality=0.9, task="saved")
    genome_store.save(saved, path)

    shared = GenomeV2()
    returned = genome_store.install(["coder"], path, genome=shared)
    assert returned is shared
    assert _row(shared, "coder")["task_observations"] == 1


def test_install_wires_the_shared_singleton_and_autosaves(tmp_path: Path) -> None:
    path = tmp_path / "genome.json"
    reset_genome_v2()
    shared = genome_store.install(["coder", "analyst"], path)
    assert shared is get_genome_v2()

    # the hook is live: mutating the shared genome writes through to disk
    get_genome_v2().observe_outcome("coder", True, task="live")
    reloaded = genome_store.load(path)
    assert _row(reloaded, "coder")["task_observations"] == 1
    assert reloaded.snapshot("analyst") is not None   # the roster was seeded


def test_install_defaults_to_resolved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "resolved.json"
    monkeypatch.setenv("NEXUS_GENOME_PATH", str(target))
    genome_store.install(["coder"], genome=GenomeV2())
    assert target.is_file()
    assert os.environ[genome_store.ENV_GENOME_PATH] == str(target)
