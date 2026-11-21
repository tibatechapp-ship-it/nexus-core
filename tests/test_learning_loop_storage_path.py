from __future__ import annotations

from pathlib import Path

from novamind.core.learning_loop import LearningLoop


def test_learning_loop_uses_dedicated_storage_path_environment(
    tmp_path: Path, monkeypatch
) -> None:
    configured = tmp_path / "isolated" / "experiences.jsonl"
    monkeypatch.setenv("NOVAMIND_HOME", str(tmp_path / "project"))
    monkeypatch.setenv("NOVAMIND_LEARNING_LOOP_PATH", str(configured))

    loop = LearningLoop()

    assert loop.storage_path == configured
    assert configured.parent.is_dir()
    assert not (tmp_path / "project" / "memory" / "experiences.jsonl").exists()


def test_learning_loop_falls_back_to_novamind_home_when_unset(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "project"
    monkeypatch.setenv("NOVAMIND_HOME", str(home))
    monkeypatch.delenv("NOVAMIND_LEARNING_LOOP_PATH", raising=False)

    loop = LearningLoop()

    assert loop.storage_path == home / "memory" / "experiences.jsonl"
    assert loop.storage_path.parent.is_dir()


def test_explicit_storage_path_takes_precedence_over_environment(
    tmp_path: Path, monkeypatch
) -> None:
    configured = tmp_path / "configured.jsonl"
    explicit = tmp_path / "explicit.jsonl"
    monkeypatch.setenv("NOVAMIND_LEARNING_LOOP_PATH", str(configured))

    loop = LearningLoop(explicit)

    assert loop.storage_path == explicit
    assert not configured.exists()
