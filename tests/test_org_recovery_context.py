"""Durable mission-context snapshot and restore tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.org.contracts import Claim, Mission, TaskSpec
from src.org.departments import MissionContext
from src.org.repo_intel import ModuleInfo, RepoMap
from src.org.review import CouncilDecision
from src.org.recovery_context import (
    fingerprint_directory,
    restore_mission_context,
    save_mission_context_snapshot,
)
from src.org.sandbox import Worktree
from src.org.store import OrgError, OrgStore


def _context(tmp_path: Path) -> tuple[OrgStore, MissionContext, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    state_root = tmp_path / "persistent-state"
    store = OrgStore(tmp_path / "org.sqlite3")
    mission = store.create_mission(Mission(
        title="resume context", objective="preserve state",
        repo_path=str(repo), status="running",
    ))
    ctx = MissionContext(mission=mission)
    ctx.worktree = Worktree.from_source(repo, files=["src/app.py"])
    ctx.originals = {"src/app.py": "VALUE = 1\n"}
    ctx.affected = {"direct": ["src/app.py"], "test_files": []}
    ctx.diff_text = "diff --git a/src/app.py b/src/app.py"
    ctx.changed_files = ["src/app.py"]
    ctx.dev_notes = "checkpointed"
    ctx.repo_map = RepoMap(
        root=str(repo),
        modules=[ModuleInfo(rel_path="src/app.py", functions=["run"])],
        languages={"python": 1},
        files_scanned=1,
    )
    ctx.council = CouncilDecision(
        verdict="approve", mean_score=95, reasons=["clean"],
        rounds=1, review_ids=["review-1"], dissent=[],
    )
    ctx.claims = [Claim(
        mission_id=mission.id, agent_role="qa:runner",
        statement="tests passed", claim_kind="test_pass",
    )]
    return store, ctx, repo, state_root


def test_context_checkpoint_restores_after_store_reopen(tmp_path: Path) -> None:
    store, ctx, repo, state_root = _context(tmp_path)
    ctx.worktree.write("src/app.py", "VALUE = 2\n")
    saved = save_mission_context_snapshot(store, ctx, state_root)
    snapshot_id = saved["id"]
    store_path = tmp_path / "org.sqlite3"
    reopened = OrgStore(store_path)

    restored = restore_mission_context(
        reopened, ctx.mission.id, state_root, expected_repo_root=repo
    )
    assert restored.mission.id == ctx.mission.id
    assert restored.originals == ctx.originals
    assert restored.affected == ctx.affected
    assert restored.diff_text == ctx.diff_text
    assert restored.changed_files == ctx.changed_files
    assert restored.dev_notes == "checkpointed"
    assert restored.repo_map is not None
    assert restored.repo_map.modules[0].functions == ["run"]
    assert restored.council is not None
    assert restored.council.verdict == "approve"
    assert restored.claims[0].statement == "tests passed"
    assert restored.worktree is not None
    assert restored.worktree.read("src/app.py") == "VALUE = 2\n"
    assert reopened.mission_context_snapshot_get(ctx.mission.id, snapshot_id)


def test_restore_rejects_source_repository_drift(tmp_path: Path) -> None:
    store, ctx, repo, state_root = _context(tmp_path)
    save_mission_context_snapshot(store, ctx, state_root)
    (repo / "src" / "app.py").write_text("VALUE = 99\n", encoding="utf-8")

    with pytest.raises(OrgError, match="بصمة المستودع تغيّرت"):
        restore_mission_context(store, ctx.mission.id, state_root)


def test_restore_rejects_worktree_drift(tmp_path: Path) -> None:
    store, ctx, _, state_root = _context(tmp_path)
    saved = save_mission_context_snapshot(store, ctx, state_root)
    Path(saved["worktree_path"], "src", "app.py").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(OrgError, match="بصمة نسخة العمل تغيّرت"):
        restore_mission_context(store, ctx.mission.id, state_root)


def test_repository_fingerprint_is_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("alpha", encoding="utf-8")
    first = fingerprint_directory(repo)
    second = fingerprint_directory(repo)
    assert first == second


def test_snapshot_rejects_repository_baseline_change_between_checkpoints(
    tmp_path: Path,
) -> None:
    store, ctx, repo, state_root = _context(tmp_path)
    save_mission_context_snapshot(store, ctx, state_root)
    (repo / "src" / "app.py").write_text("changed by operator\n", encoding="utf-8")

    with pytest.raises(OrgError, match="بصمة المستودع تغيّرت منذ أول checkpoint"):
        save_mission_context_snapshot(store, ctx, state_root)


def test_restore_rejects_task_ledger_newer_than_context_checkpoint(
    tmp_path: Path,
) -> None:
    store, ctx, _, state_root = _context(tmp_path)
    task = store.add_task(TaskSpec(
        mission_id=ctx.mission.id, dept="executive", kind="requirements",
        description="record task completion",
    ))
    save_mission_context_snapshot(store, ctx, state_root)
    store.task_set_state(task.id, "done", result={"completed": True}, attempts=1)

    with pytest.raises(OrgError, match="سجل المهام تغيّر بعد آخر checkpoint"):
        restore_mission_context(store, ctx.mission.id, state_root)
