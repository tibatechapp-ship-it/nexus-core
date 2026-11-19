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
        mission=SimpleNamespace(status="running", phase="G_RELEASE"),
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
    report = tmp_path / "REPORT.md"
    report.write_text("# Mission report\n", encoding="utf-8")
    mission = SimpleNamespace(id="mission-1", status="done", phase="G_RELEASE", repo_path=str(repo), report_path=str(report))
    store = Store(mission)
    sink = Sink()
    baseline = _baseline(sink)
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: _context(source))

    def fake_execute(**kwargs):
        workspaces = [item.workspace for item in kwargs["cases"]]
        assert len(set(workspaces)) == 2
        assert all((path / "app.py").is_file() for path in workspaces)
        assert all(path != source for path in workspaces)
        for case in kwargs["cases"]:
            assert case.argv[-1] == "/workspace/.nexus-behavior/input.json"
            assert (case.workspace / ".nexus-behavior" / "input.json").is_file()
        return (
            CapturedCase("health", {"path": "/health"}, {"status": 200}),
            CapturedCase("extra", {"path": "/extra"}, {"status": 404}),
        )

    monkeypatch.setattr(module, "execute_authorized_cases", fake_execute)
    result = run_mission_behavior_replay(
        store=store, mission_id="mission-1", state_root=state,
        baseline=baseline,
        cases=[
            BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {"path": "/health"}),
            BehaviorCaseSpec("extra", ("cat", "{behavior_input}"), {"path": "/extra"}),
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
        "behavior.replay.requested",
        "behavior.replay.report_persisted",
        "behavior.replay.completed",
    ]
    report_text = report.read_text(encoding="utf-8")
    assert "## التحقق السلوكي" in report_text
    assert '"verdict": "invalid"' in report_text
    assert result.candidate_revision in report_text
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
            cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: True,
        )
    assert store.audit_events == [(
        "behavior.replay.failed", "mission-1", {
            "error_type": "MissionBehaviorError",
            "error": "behavior replay is allowed only for an existing completed mission",
        }
    )]


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
            cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: False,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"



def test_mission_replay_rejects_checkpoint_from_earlier_phase(tmp_path, monkeypatch):
    import src.intelligence.mission as module
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    store = Store(SimpleNamespace(
        id="mission-1", status="done", phase="G_RELEASE", repo_path=str(repo)
    ))
    context = _context(checkpoint)
    context.mission = SimpleNamespace(status="running", phase="E_TESTING")
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: context)
    monkeypatch.setattr(
        module, "execute_authorized_cases",
        lambda **kwargs: pytest.fail("stale checkpoint must not execute"),
    )
    sink = Sink()
    with pytest.raises(MissionBehaviorError, match="final pre-completion"):
        run_mission_behavior_replay(
            store=store, mission_id="mission-1", state_root=state,
            baseline=_baseline(sink),
            cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: True,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"



def test_behavior_case_spec_requires_fixture_placeholder():
    with pytest.raises(MissionBehaviorError, match="behavior_input"):
        BehaviorCaseSpec("health", ("python", "-V"), {})



def test_snapshot_copy_rejects_symlink_directory(tmp_path):
    import src.intelligence.mission as module
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (source / "linked-dir").symlink_to(outside, target_is_directory=True)
    with pytest.raises(MissionBehaviorError, match="symlink directory"):
        module._copy_verified_snapshot(source, tmp_path / "copy")


def test_snapshot_copy_rejects_nonregular_file(tmp_path):
    import os
    import src.intelligence.mission as module
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO files are not supported on this platform")
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "pipe")
    with pytest.raises(MissionBehaviorError, match="non-regular file"):
        module._copy_verified_snapshot(source, tmp_path / "copy")


def test_behavior_case_spec_rejects_invalid_identity_args_timeout_and_fixture() -> None:
    with pytest.raises(MissionBehaviorError, match="non-empty"):
        BehaviorCaseSpec(" ", ("cat", "{behavior_input}"), {})
    with pytest.raises(MissionBehaviorError, match="invalid argument"):
        BehaviorCaseSpec("case", ("cat", 7, "{behavior_input}"), {})
    with pytest.raises(MissionBehaviorError, match="timeout"):
        BehaviorCaseSpec("case", ("cat", "{behavior_input}"), {}, timeout=True)
    with pytest.raises(MissionBehaviorError, match="fixture is invalid"):
        BehaviorCaseSpec("case", ("cat", "{behavior_input}"), object())


def test_report_append_handles_missing_duplicate_and_oversized_report(tmp_path) -> None:
    from src.intelligence.behavior import BehaviorComparison
    from src.intelligence.mission import (
        MissionBehaviorReplayResult, _append_behavior_report,
    )
    result = MissionBehaviorReplayResult(
        "mission-1", "base", "candidate",
        BehaviorComparison(BehaviorVerdict.EQUIVALENT, ("matched",)),
        ("ev-1",),
    )
    assert _append_behavior_report(SimpleNamespace(), result, "run-1") is False

    missing = tmp_path / "missing.md"
    with pytest.raises(MissionBehaviorError, match="missing or is not a regular file"):
        _append_behavior_report(SimpleNamespace(report_path=str(missing)), result, "run-1")

    report = tmp_path / "report.md"
    report.write_text("# Report\n", encoding="utf-8")
    assert _append_behavior_report(SimpleNamespace(report_path=str(report)), result, "run-1")
    with pytest.raises(MissionBehaviorError, match="already present"):
        _append_behavior_report(SimpleNamespace(report_path=str(report)), result, "run-1")

    huge = tmp_path / "huge.md"
    huge.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(MissionBehaviorError, match="2 MiB"):
        _append_behavior_report(SimpleNamespace(report_path=str(huge)), result, "run-2")


def test_snapshot_copy_skips_generated_dirs_and_rejects_sensitive_suffix(tmp_path) -> None:
    import src.intelligence.mission as module
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('ok')", encoding="utf-8")
    generated = source / "node_modules"
    generated.mkdir()
    (generated / "ignored.js").write_text("ignored", encoding="utf-8")
    destination = tmp_path / "copy"
    module._copy_verified_snapshot(source, destination)
    assert (destination / "app.py").is_file()
    assert not (destination / "node_modules").exists()

    (source / "private.pem").write_text("private", encoding="utf-8")
    with pytest.raises(MissionBehaviorError, match="credential-like"):
        module._copy_verified_snapshot(source, tmp_path / "copy-2")


def test_stage_behavior_input_rejects_non_json_oversized_and_existing_path(tmp_path) -> None:
    import src.intelligence.mission as module
    with pytest.raises(MissionBehaviorError, match="canonical JSON"):
        module._stage_behavior_input(tmp_path, object())

    too_large = tmp_path / "large"
    too_large.mkdir()
    with pytest.raises(MissionBehaviorError, match="1 MiB"):
        module._stage_behavior_input(too_large, "x" * (1024 * 1024 + 1))

    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / ".nexus-behavior").mkdir()
    with pytest.raises(FileExistsError):
        module._stage_behavior_input(existing, {})


def test_mission_replay_rejects_state_root_inside_repository(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / ".nexus-state"
    state.mkdir()
    store = Store(SimpleNamespace(
        id="mission-1", status="done", phase="G_RELEASE", repo_path=str(repo)
    ))
    sink = Sink()
    with pytest.raises(MissionBehaviorError, match="outside the target repository"):
        run_mission_behavior_replay(
            store=store, mission_id="mission-1", state_root=state,
            baseline=_baseline(sink),
            cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: True,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"


def test_mission_replay_rejects_missing_checkpoint_worktree(tmp_path, monkeypatch) -> None:
    import src.intelligence.mission as module
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    context = _context(checkpoint)
    context.worktree = None
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: context)
    store = Store(SimpleNamespace(
        id="mission-1", status="done", phase="G_RELEASE", repo_path=str(repo)
    ))
    sink = Sink()
    with pytest.raises(MissionBehaviorError, match="no verified worktree"):
        run_mission_behavior_replay(
            store=store, mission_id="mission-1", state_root=state,
            baseline=_baseline(sink),
            cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: True,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"


def test_mission_replay_wraps_runner_failure_and_cleans_workspace(tmp_path, monkeypatch) -> None:
    import src.intelligence.mission as module
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "app.py").write_text("pass", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    context = _context(checkpoint)
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: context)
    monkeypatch.setattr(
        module, "execute_authorized_cases",
        lambda **kwargs: (_ for _ in ()).throw(OSError("runner unavailable")),
    )
    store = Store(SimpleNamespace(
        id="mission-1", status="done", phase="G_RELEASE", repo_path=str(repo)
    ))
    sink = Sink()
    with pytest.raises(MissionBehaviorError, match="failed closed"):
        run_mission_behavior_replay(
            store=store, mission_id="mission-1", state_root=state,
            baseline=_baseline(sink),
            cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {})],
            run_id="candidate-run", collected_by="test", evidence_sink=sink,
            verify_evidence=lambda _: True,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"
    assert not list(state.glob("behavior-*"))


def test_mission_replay_reports_unavailable_for_legacy_mission(tmp_path, monkeypatch) -> None:
    import src.intelligence.mission as module
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "app.py").write_text("pass", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(module, "restore_mission_context", lambda *a, **k: _context(checkpoint))
    monkeypatch.setattr(
        module, "execute_authorized_cases",
        lambda **kwargs: (
            CapturedCase("health", {"path": "/health"}, {"status": 200}),
        ),
    )
    store = Store(SimpleNamespace(
        id="mission-1", status="done", phase="G_RELEASE", repo_path=str(repo)
    ))
    sink = Sink()
    result = run_mission_behavior_replay(
        store=store, mission_id="mission-1", state_root=state,
        baseline=_baseline(sink),
        cases=[BehaviorCaseSpec("health", ("cat", "{behavior_input}"), {"path": "/health"})],
        run_id="candidate-run", collected_by="test", evidence_sink=sink,
        verify_evidence=lambda ref: (
            ref.evidence_id in sink.items
            and hashlib.sha256(sink.items[ref.evidence_id]).hexdigest() == ref.sha256
        ),
    )
    assert result.comparison.verdict is BehaviorVerdict.EQUIVALENT
    assert any(event[0] == "behavior.replay.report_unavailable" for event in store.audit_events)
