"""Tests for src.patterns.checkpoint — resumable pipeline runs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from src.agents.base import BaseAgent
from src.core.types import Message
from src.patterns.checkpoint import CheckpointStore, StageCheckpoint
from src.patterns.pipeline import Pipeline


class _ScriptedBackend:
    """Returns canned outputs in order; tracks how often it was called."""

    def __init__(self, *outputs: str) -> None:
        self._outputs = list(outputs) or [""]
        self.calls = 0
        self.seen: list[str] = []

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        self.seen.append(messages[-1].content)
        output = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return output

    def seen_call(self) -> str:
        """The last user turn this backend was handed."""
        return self.seen[-1] if self.seen else ""


class _FailBackend:
    """Always raises — models a stage that fails."""

    def generate(self, messages: Sequence[Message], *, model: str | None = None) -> str:
        raise RuntimeError("boom")


def _agent(name: str, backend: object) -> BaseAgent:
    agent = BaseAgent(backend)  # type: ignore[arg-type]
    agent.name = name
    return agent


def _checkpoint(run_id: str, stage: int, *, ok: bool = True, agent: str = "a", output: str = "saved", error: str | None = None) -> StageCheckpoint:
    return StageCheckpoint(
        run_id=run_id, stage=stage, agent=agent, ok=ok, output=output, error=error, duration_s=1.0
    )


# ── StageCheckpoint ───────────────────────────────────────────────────────
def test_stage_checkpoint_roundtrip() -> None:
    checkpoint = _checkpoint("r1", 2, agent="coder", output="done", error=None)
    restored = StageCheckpoint.from_dict(checkpoint.to_dict())
    assert restored == checkpoint


def test_stage_checkpoint_from_dict_tolerates_gaps() -> None:
    restored = StageCheckpoint.from_dict({"run_id": "r", "stage": "3", "agent": "a", "ok": "true"})
    assert restored.run_id == "r"
    assert restored.stage == 3
    assert restored.ok is True
    assert restored.output == ""
    assert restored.error is None


# ── CheckpointStore (in-memory) ───────────────────────────────────────────
def test_store_save_and_read() -> None:
    store = CheckpointStore()
    store.save(_checkpoint("r1", 0))
    store.save(_checkpoint("r1", 1, agent="b", output="second"))
    store.save(_checkpoint("r2", 0, agent="c"))

    assert len(store) == 3
    assert store.runs() == ["r1", "r2"]
    assert store.stage("r1", 0) is not None
    assert store.stage("r1", 0).output == "saved"  # type: ignore[union-attr]
    assert store.stage("r1", 5) is None
    assert sorted(store.stages("r1")) == [0, 1]


def test_store_completed_stage_requires_success() -> None:
    store = CheckpointStore()
    store.save(_checkpoint("r1", 0, ok=True))
    store.save(_checkpoint("r1", 1, ok=False, error="boom"))
    assert store.completed_stage("r1", 0) is not None
    assert store.completed_stage("r1", 1) is None  # failed → retried on resume


def test_store_overwrite_same_stage() -> None:
    store = CheckpointStore()
    store.save(_checkpoint("r1", 0, output="first"))
    store.save(_checkpoint("r1", 0, output="second"))
    assert len(store) == 1
    assert store.stage("r1", 0).output == "second"  # type: ignore[union-attr]


def test_store_clear() -> None:
    store = CheckpointStore()
    store.save(_checkpoint("r1", 0))
    store.save(_checkpoint("r2", 0))
    assert store.clear("r1") == 1
    assert store.clear("r1") == 0
    assert store.runs() == ["r2"]


# ── CheckpointStore (file persistence) ────────────────────────────────────
def test_store_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    CheckpointStore(path).save(_checkpoint("r1", 0, agent="coder", output="kept"))

    reloaded = CheckpointStore(path)
    checkpoint = reloaded.stage("r1", 0)
    assert checkpoint is not None
    assert checkpoint.agent == "coder" and checkpoint.output == "kept"
    assert len(reloaded) == 1


def test_store_created_missing_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "cp.json"
    store = CheckpointStore(path)
    store.save(_checkpoint("r1", 0))
    assert path.exists()
    assert CheckpointStore(path).stage("r1", 0) is not None


def test_store_ignores_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    path.write_text("{ not json", encoding="utf-8")
    assert len(CheckpointStore(path)) == 0


def test_store_ignores_non_dict_payload_and_malformed_rows(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    path.write_text(json.dumps({"r1": {"0": "not-a-checkpoint"}, "r2": [1, 2]}), encoding="utf-8")
    store = CheckpointStore(path)
    assert len(store) == 0
    assert store.runs() == []


def test_store_write_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    store = CheckpointStore(path)
    store.save(_checkpoint("r1", 0))
    assert not list(tmp_path.glob("*.tmp"))  # no leftover temp file


# ── Pipeline resumption ───────────────────────────────────────────────────
def test_pipeline_without_store_is_unchanged() -> None:
    first = _agent("a", _ScriptedBackend("A"))
    second = _agent("b", _ScriptedBackend("B"))
    pipe = Pipeline([first, second])
    result = pipe.run("t", run_id="ignored")
    assert result.output == "B"
    assert pipe.run_id == "ignored"


def test_pipeline_resumes_skipping_completed_stages(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "cp.json")
    # Stage 0 finished in a previous run.
    store.save(_checkpoint("run-7", 0, agent="a", output="A"))
    first = _agent("a", _ScriptedBackend("A"))
    second = _agent("b", _ScriptedBackend("B"))

    pipe = Pipeline([first, second], checkpoints=store)
    result = pipe.run("t", run_id="run-7")

    assert result.output == "B"
    assert first.backend.calls == 0  # stage skipped — not re-executed
    assert second.backend.calls == 1
    assert store.stage("run-7", 1) is not None  # new stage recorded


def test_pipeline_resume_chains_saved_output_into_next_stage(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "cp.json")
    store.save(_checkpoint("r", 0, agent="a", output="saved context"))
    first = _agent("a", _ScriptedBackend("A"))
    second_backend = _ScriptedBackend("B")
    second = _agent("b", second_backend)

    pipe = Pipeline([first, second], checkpoints=store)
    result = pipe.run("t", run_id="r")

    assert result.output == "B"
    assert "saved context" in second_backend.seen_call()


def test_pipeline_retries_failed_stage_on_resume(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "cp.json")
    store.save(_checkpoint("r", 0, ok=False, agent="a", error="boom"))
    first = _agent("a", _ScriptedBackend("A"))
    second = _agent("b", _ScriptedBackend("B"))

    pipe = Pipeline([first, second], checkpoints=store)
    result = pipe.run("t", run_id="r")

    assert result.output == "B"
    assert first.backend.calls == 1  # failed stage re-executed
    assert store.completed_stage("r", 0) is not None  # now marked done


def test_pipeline_saves_partial_progress_after_failure(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "cp.json")
    first = _agent("a", _ScriptedBackend("A"))
    bad = _agent("bad", _FailBackend())

    pipe = Pipeline([first, bad], checkpoints=store)
    result = pipe.run("t", run_id="r")

    assert not result.ok
    assert store.completed_stage("r", 0) is not None  # successful stage saved
    assert store.stage("r", 1) is not None and store.stage("r", 1).ok is False


def test_pipeline_resume_stops_at_failed_saved_stage(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "cp.json")
    store.save(_checkpoint("r", 0, agent="a", output="saved ok"))
    # a fresh run whose stage 1 fails mid-way
    first = _agent("a", _ScriptedBackend("A"))
    bad = _agent("bad", _FailBackend())
    pipe = Pipeline([first, bad], checkpoints=store)
    pipe.run("t", run_id="r")
    # resume again: stage 0 skipped, stage 1 retried and fails again
    resume = Pipeline([first, bad], checkpoints=store)
    result = resume.run("t", run_id="r")
    assert not result.ok
    assert first.backend.calls == 0


def test_pipeline_clear_run_allows_clean_restart(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "cp.json")
    store.save(_checkpoint("r", 0, agent="a", output="saved"))
    first = _agent("a", _ScriptedBackend("A"))
    pipe = Pipeline([first, _agent("b", _ScriptedBackend("B"))], checkpoints=store)

    store.clear("r")
    pipe.run("t", run_id="r")
    assert first.backend.calls == 1  # cleared → stage re-executed