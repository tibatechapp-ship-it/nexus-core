"""Mission lifecycle integration tests for explicit behavior replay."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.intelligence import EvidenceReference
from src.intelligence.behavior import BehaviorVerdict
from src.intelligence.capture import CapturedCase, capture_baseline
from src.intelligence.mission import (
    BehaviorCaseSpec, MissionBehaviorError, run_mission_behavior_replay,
)


class Sink:
    def __init__(self):
        self.items = {}

    def put(self, evidence_id, payload, *, kind, collected_by):
        self.items[evidence_id] = payload
        return EvidenceReference(
            evidence_id, kind, f"memory://{evidence_id}",
            hashlib.sha256(payload).hexdigest(), collected_by,
        )


class Store:
    def __init__(self, mission):
        self.mission = mission
        self.audit_events = []

    def mission_get(self, mission_id):
        return self.mission if self.mission.id == mission_id else None

    def approvals_for(self, mission_id):
        return []

    def audit(self, action, ref="", details=None, actor="org"):
        self.audit_events.append((action, ref, details or {}))


def _baseline(sink, mission_id="mission-1"):
    return capture_baseline(
        target=f"mission:{mission_id}", revision="baseline-rev",
        run_id="baseline-run",
        cases=[CapturedCase("health", {"path": "/health"}, {"status": 200})],
        collected_by="baseline-harness", sink=sink,
    )


def _context(worktree):
    return SimpleNamespace(
        execution_policy={
            "schema_version": 1, "execution_mode": "container",
            "container_enabled": True,
            "container_image": "registry.example/runner@sha256:" + "a" * 64,
            "approval_id": "approval-1",
        },
        worktree=SimpleNamespace(root=worktree),
    )


def test_mission_replay_restores_snapshot_copies_per_case_and_audits(
    tmp_path, monkeypatch
):
    import src.intelligence.mission as module
    source = tmp_path / "checkpoint"
    source.mkdir()
    (source / "app.py").write_text("print('ok')", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    mission = SimpleNamespace(id="mission-1", status="done", repo_path=str(repo))
    store = Store(mission)
    sink = Sink()
    baseline = _baseline(sink)
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: _context(source))

    def fake_execute(**kwargs):
        workspaces = [item.workspace for item in kwargs["cases"]]
        assert len(set(workspaces)) == 2
        assert all((path / "app.py").is_file() for path in workspaces)
        assert all(path != source for path in workspaces)
        return (
            CapturedCase("health", {"path": "/health"}, {"status": 200}),
            CapturedCase("extra", {"path": "/extra"}, {"status": 404}),
        )

    monkeypatch.setattr(module, "execute_authorized_cases", fake_execute)
    result = run_mission_behavior_replay(
        store=store, mission_id="mission-1", state_root=state,
        baseline=baseline,
        cases=[
            BehaviorCaseSpec("health", ("python", "-V"), {"path": "/health"}),
            BehaviorCaseSpec("extra", ("python", "-V"), {"path": "/extra"}),
        ],
        run_id="candidate-run", collected_by="replay-harness",
        evidence_sink=sink,
        verify_evidence=lambda ref: (
            ref.evidence_id in sink.items
            and hashlib.sha256(sink.items[ref.evidence_id]).hexdigest() == ref.sha256
        ),
    )
    assert result.comparison.verdict is BehaviorVerdict.INVALID
    assert [item[0] for item in store.audit_events] == [
        "behavior.replay.requested", "behavior.replay.completed"
    ]
    assert not list(state.glob("behavior-*"))


def test_mission_replay_rejects_noncompleted_mission_before_restore(tmp_path, monkeypatch):
    import src.intelligence.mission as module
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    store = Store(SimpleNamespace(id="mission-1", status="running", repo_path=str(repo)))
    monkeypatch.setattr(
        module, "restore_mission_context",
        lambda *a, **k: pytest.fail("checkpoint must not be restored"),
    )
    sink = Sink()
    with pytest.raises(MissionBehaviorError, match="completed mission"):
        run_mission_behavior_replay(
            store=store, mission_id="mission-1", state_root=state,
            baseline=_baseline(sink),
            cases=[BehaviorCaseSpec("health", ("python", "-V"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: True,
        )
    assert store.audit_events[-1][0] == "behavior.replay.requested"


def test_snapshot_copy_rejects_credentials(tmp_path):
    import src.intelligence.mission as module
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env").write_text("SECRET=value", encoding="utf-8")
    with pytest.raises(MissionBehaviorError, match="credential-like"):
        module._copy_verified_snapshot(source, tmp_path / "copy")


def test_snapshot_copy_rejects_symlink(tmp_path):
    import src.intelligence.mission as module
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("not copied", encoding="utf-8")
    (source / "linked").symlink_to(outside)
    with pytest.raises(MissionBehaviorError, match="symlink"):
        module._copy_verified_snapshot(source, tmp_path / "copy")



def test_mission_replay_verifies_baseline_before_invoking_runner(tmp_path, monkeypatch):
    import src.intelligence.mission as module
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    store = Store(SimpleNamespace(id="mission-1", status="done", repo_path=str(repo)))
    sink = Sink()
    baseline = _baseline(sink)
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: _context(checkpoint))
    monkeypatch.setattr(
        module, "execute_authorized_cases",
        lambda **kwargs: pytest.fail("candidate must not execute with unverified baseline"),
    )
    with pytest.raises(MissionBehaviorError, match="baseline evidence"):
        run_mission_behavior_replay(
            store=store, mission_id="mission-1", state_root=state,
            baseline=baseline,
            cases=[BehaviorCaseSpec("health", ("python", "-V"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: False,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"
