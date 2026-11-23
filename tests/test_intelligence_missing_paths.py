"""Regression tests for uncovered fail-closed intelligence branches."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.intelligence import EvidenceReference, IntelligenceResult, ResultStatus
from src.intelligence.behavior import (
    BehaviorBaseline, BehaviorCase, BehaviorComparison, BehaviorContractError,
    BehaviorObservation, BehaviorVerdict, ObservationStatus, compare_behavior,
    digest_payload,
)
from src.intelligence.capture import (
    CaptureError, CapturedCase, capture_baseline, capture_observations,
)
from src.intelligence.gate import AssuranceVerdict, evaluate_assurance
from src.intelligence.mission import (
    BehaviorCaseSpec, MissionBehaviorError, MissionBehaviorReplayResult,
    _append_behavior_report, _copy_verified_snapshot, _is_sensitive_name,
    run_mission_behavior_replay,
)
from src.intelligence.replay import (
    BehaviorReplayError, ReplayCommandCase, _approved_image,
    execute_authorized_cases,
)


_SHA = "a" * 64
_OUT = "b" * 64
_IMAGE = "registry.example/runner@sha256:" + "c" * 64


class _Sink:
    def __init__(self):
        self.items = {}

    def put(self, evidence_id, payload, *, kind, collected_by):
        self.items[evidence_id] = payload
        return EvidenceReference(
            evidence_id, kind, f"memory://{evidence_id}",
            hashlib.sha256(payload).hexdigest(), collected_by,
        )


class _Store:
    def __init__(self, mission):
        self.mission = mission
        self.audit_events = []

    def mission_get(self, mission_id):
        return self.mission if self.mission and self.mission.id == mission_id else None

    def approvals_for(self, mission_id):
        return []

    def audit(self, action, ref="", details=None, actor="org"):
        self.audit_events.append((action, ref, details or {}))


def _ref(evidence_id="base-ev", digest=_SHA):
    return EvidenceReference(evidence_id, "test", f"memory://{evidence_id}", digest, "test")


def _baseline(target="mission:case-1", refs=None):
    evidence = tuple(refs or (_ref(),))
    return BehaviorBaseline(
        target, "base-rev",
        (BehaviorCase("case-1", _SHA, _OUT, evidence[0].evidence_id),),
        evidence,
    )


def _mission_result(reason="ok"):
    from src.intelligence.behavior import BehaviorGateDecision, BehaviorGateVerdict
    from src.intelligence.gate import AssuranceDecision
    return MissionBehaviorReplayResult(
        "case-1", "base", "candidate",
        BehaviorComparison(BehaviorVerdict.EQUIVALENT, (reason,)),
        AssuranceDecision(AssuranceVerdict.ASSURED, ("verified",), ("base-ev",)),
        BehaviorGateDecision(BehaviorGateVerdict.ASSURED, ("passed",)),
        ("base-ev",),
    )


def _replay_context(worktree):
    return SimpleNamespace(
        mission=SimpleNamespace(status="running", phase="G_RELEASE"),
        execution_policy={
            "schema_version": 1, "execution_mode": "container",
            "container_enabled": True, "container_image": _IMAGE,
            "approval_id": "approval-1",
        },
        worktree=SimpleNamespace(root=worktree),
    )


def test_case_spec_rejects_empty_command_and_wrong_placeholder_count():
    with pytest.raises(MissionBehaviorError, match="between 1 and 128"):
        BehaviorCaseSpec("case", (), {})
    with pytest.raises(MissionBehaviorError, match="exactly one"):
        BehaviorCaseSpec("case", ("python", "-V"), {})
    with pytest.raises(MissionBehaviorError, match="exactly one"):
        BehaviorCaseSpec("case", ("{behavior_input}", "{behavior_input}"), {})


def test_report_append_rejects_symlink_and_oversized_section(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# report\n", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(report)
    with pytest.raises(MissionBehaviorError, match="missing or is not a regular file"):
        _append_behavior_report(SimpleNamespace(report_path=str(link)), _mission_result(), "run-link")
    base = _mission_result()
    huge = MissionBehaviorReplayResult(
        base.mission_id, base.baseline_revision, "x" * (130 * 1024),
        base.comparison, base.assurance, base.gate_decision, base.evidence_ids,
    )
    with pytest.raises(MissionBehaviorError, match="128 KiB"):
        _append_behavior_report(SimpleNamespace(report_path=str(report)), huge, "run-huge")


def test_report_append_cleans_temp_file_when_atomic_replace_fails(tmp_path, monkeypatch):
    import src.intelligence.mission as mission_module
    report = tmp_path / "report.md"
    report.write_text("# report\n", encoding="utf-8")
    monkeypatch.setattr(mission_module.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        _append_behavior_report(SimpleNamespace(report_path=str(report)), _mission_result(), "run-replace")
    assert list(tmp_path.glob(".nexus-report-*.tmp")) == []


def test_snapshot_rejects_root_symlink_and_non_directory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "source-link"
    link.symlink_to(source, target_is_directory=True)
    with pytest.raises(MissionBehaviorError, match="root must not be a symlink"):
        _copy_verified_snapshot(link, tmp_path / "copy-link")
    regular = tmp_path / "file"
    regular.write_text("x", encoding="utf-8")
    with pytest.raises(MissionBehaviorError, match="real directory"):
        _copy_verified_snapshot(regular, tmp_path / "copy-file")


def test_snapshot_file_and_byte_limits_are_enforced(tmp_path, monkeypatch):
    import src.intelligence.mission as mission_module
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("123", encoding="utf-8")
    (source / "two.txt").write_text("4", encoding="utf-8")
    monkeypatch.setattr(mission_module, "_MAX_SNAPSHOT_FILES", 1)
    with pytest.raises(MissionBehaviorError, match="copy limits"):
        _copy_verified_snapshot(source, tmp_path / "copy-count")
    monkeypatch.setattr(mission_module, "_MAX_SNAPSHOT_FILES", 10)
    monkeypatch.setattr(mission_module, "_MAX_SNAPSHOT_BYTES", 2)
    with pytest.raises(MissionBehaviorError, match="copy limits"):
        _copy_verified_snapshot(source, tmp_path / "copy-bytes")


def test_sensitive_filename_policy_allows_templates_but_rejects_credentials():
    assert _is_sensitive_name(".env") is True
    assert _is_sensitive_name(".env.production") is True
    assert _is_sensitive_name(".env.example") is False
    assert _is_sensitive_name("private.pem") is True
    assert _is_sensitive_name("module.py") is False


def test_mission_replay_rejects_invalid_request_preconditions(tmp_path):
    valid = _baseline()
    valid_case = BehaviorCaseSpec("case-1", ("cat", "{behavior_input}"), {})
    kwargs = dict(
        store=None, mission_id="case-1", state_root=tmp_path,
        baseline=valid, cases=[valid_case], run_id="run",
        collected_by="test", evidence_sink=_Sink(), verify_evidence=lambda _: True,
    )
    with pytest.raises(MissionBehaviorError, match="mission ID"):
        run_mission_behavior_replay(**{**kwargs, "mission_id": " "})
    with pytest.raises(MissionBehaviorError, match="valid behavior baseline"):
        run_mission_behavior_replay(**{**kwargs, "baseline": None})
    with pytest.raises(MissionBehaviorError, match="not bound"):
        run_mission_behavior_replay(**{**kwargs, "baseline": _baseline("mission:other")})
    with pytest.raises(MissionBehaviorError, match="between 1 and 1000"):
        run_mission_behavior_replay(**{**kwargs, "cases": []})
    with pytest.raises(MissionBehaviorError, match="invalid case declaration"):
        run_mission_behavior_replay(**{**kwargs, "cases": [object()]})
    with pytest.raises(MissionBehaviorError, match="duplicate case IDs"):
        run_mission_behavior_replay(**{**kwargs, "cases": [valid_case, valid_case]})
    with pytest.raises(MissionBehaviorError, match="verifier is required"):
        run_mission_behavior_replay(**{**kwargs, "verify_evidence": None})
    with pytest.raises(MissionBehaviorError, match="run_id"):
        run_mission_behavior_replay(**{**kwargs, "run_id": " "})
    with pytest.raises(MissionBehaviorError, match="immutable evidence sink"):
        run_mission_behavior_replay(**{**kwargs, "evidence_sink": object()})


def test_mission_replay_verifier_exception_fails_closed(tmp_path, monkeypatch):
    import src.intelligence.mission as mission_module
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    store = _Store(SimpleNamespace(id="case-1", status="done", phase="G_RELEASE", repo_path=str(repo)))
    monkeypatch.setattr(mission_module, "restore_mission_context", lambda *a, **k: pytest.fail("restore must not happen"))
    with pytest.raises(MissionBehaviorError, match="baseline evidence"):
        run_mission_behavior_replay(
            store=store, mission_id="case-1", state_root=state,
            baseline=_baseline(), cases=[BehaviorCaseSpec("case-1", ("cat", "{behavior_input}"), {})],
            run_id="run", collected_by="test", evidence_sink=_Sink(),
            verify_evidence=lambda _: (_ for _ in ()).throw(RuntimeError("evidence unavailable")),
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"


def test_mission_replay_enforces_combined_evidence_limit(tmp_path, monkeypatch):
    import src.intelligence.mission as mission_module
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "app.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(mission_module, "_MAX_COMBINED_EVIDENCE", 1)
    baseline = _baseline()
    store = _Store(SimpleNamespace(id="case-1", status="done", phase="G_RELEASE", repo_path=str(repo)))
    monkeypatch.setattr(mission_module, "restore_mission_context", lambda *a, **k: _replay_context(checkpoint))
    monkeypatch.setattr(
        mission_module, "execute_authorized_cases",
        lambda **kwargs: (CapturedCase("case-1", {}, {"ok": True}),),
    )
    with pytest.raises(MissionBehaviorError, match="combined baseline and candidate evidence"):
        run_mission_behavior_replay(
            store=store, mission_id="case-1", state_root=state,
            baseline=baseline, cases=[BehaviorCaseSpec("case-1", ("cat", "{behavior_input}"), {})],
            run_id="candidate", collected_by="test", evidence_sink=_Sink(),
            verify_evidence=lambda _: True,
        )
    assert store.audit_events[-1][0] == "behavior.replay.failed"


def test_replay_command_validation_and_approval_store_failures(tmp_path):
    with pytest.raises(BehaviorReplayError, match="non-empty"):
        ReplayCommandCase(" ", ("python",), tmp_path, {})
    with pytest.raises(BehaviorReplayError, match="filesystem path"):
        ReplayCommandCase("case", ("python",), object(), {})
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(BehaviorReplayError, match="non-symlink"):
        ReplayCommandCase("case", ("python",), link, {})
    with pytest.raises(BehaviorReplayError, match="timeout"):
        ReplayCommandCase("case", ("python",), tmp_path, {}, timeout=True)
    with pytest.raises(BehaviorReplayError, match="fixture is invalid"):
        ReplayCommandCase("case", ("python",), tmp_path, object())

    policy = {
        "schema_version": 1, "execution_mode": "container",
        "container_enabled": True, "container_image": _IMAGE,
        "approval_id": "approval-1",
    }
    with pytest.raises(BehaviorReplayError, match="explicit mission execution policy"):
        _approved_image("mission", None, object())
    with pytest.raises(BehaviorReplayError, match="not explicitly enabled"):
        _approved_image("mission", {**policy, "container_enabled": False}, object())
    with pytest.raises(BehaviorReplayError, match="approval store is unavailable"):
        _approved_image("mission", policy, object())
    class RaisingStore:
        def approvals_for(self, mission_id):
            raise OSError("db down")
    with pytest.raises(BehaviorReplayError, match="could not retrieve"):
        _approved_image("mission", policy, RaisingStore())
    class MalformedStore:
        def approvals_for(self, mission_id):
            return "not-a-list"
    with pytest.raises(BehaviorReplayError, match="malformed records"):
        _approved_image("mission", policy, MalformedStore())
    class DuplicateStore:
        def approvals_for(self, mission_id):
            approval = SimpleNamespace(
                id="approval-1", kind="run_untrusted", approved=True,
                decided_by="human", subject=_IMAGE,
            )
            return [approval, approval]
    with pytest.raises(BehaviorReplayError, match="exactly one"):
        _approved_image("mission", policy, DuplicateStore())


def test_replay_runner_exception_and_invalid_status_fail_closed(tmp_path, monkeypatch):
    import src.intelligence.replay as replay_module
    workspace = tmp_path / "case"
    workspace.mkdir()
    case = ReplayCommandCase("case", ("python", "-V"), workspace, {})
    approval = SimpleNamespace(
        id="approval-1", kind="run_untrusted", approved=True,
        decided_by="human", subject=_IMAGE,
    )
    store = SimpleNamespace(approvals_for=lambda _: [approval])
    policy = {
        "schema_version": 1, "execution_mode": "container",
        "container_enabled": True, "container_image": _IMAGE,
        "approval_id": "approval-1",
    }
    monkeypatch.setattr(replay_module, "run_in_container", lambda *a, **k: (_ for _ in ()).throw(OSError("sandbox down")))
    with pytest.raises(BehaviorReplayError, match="failed closed"):
        execute_authorized_cases(mission_id="mission", execution_policy=policy, approval_store=store, cases=[case])
    monkeypatch.setattr(replay_module, "run_in_container", lambda *a, **k: {
        "ok": "yes", "exit_code": 0, "timeout": False, "truncated": False,
        "stdout": "", "stderr": "",
    })
    with pytest.raises(BehaviorReplayError, match="invalid status fields"):
        execute_authorized_cases(mission_id="mission", execution_policy=policy, approval_store=store, cases=[case])


def test_behavior_contract_rejects_duplicate_ids_and_malformed_serialization():
    ref = _ref()
    case = BehaviorCase("case", _SHA, _OUT, ref.evidence_id)
    with pytest.raises(BehaviorContractError, match="duplicate case IDs"):
        BehaviorBaseline("target", "rev", (case, case), (ref,))
    with pytest.raises(BehaviorContractError, match="duplicate evidence IDs"):
        BehaviorBaseline("target", "rev", (case,), (ref, ref))
    with pytest.raises(BehaviorContractError, match="cases and evidence must be arrays"):
        BehaviorBaseline.from_dict({"target": "t", "revision": "r", "cases": {}, "evidence": []})
    with pytest.raises(BehaviorContractError, match="unknown or missing fields"):
        BehaviorBaseline.from_dict({
            "target": "t", "revision": "r",
            "cases": [{"case_id": "c", "input_sha256": _SHA, "output_sha256": _OUT, "evidence_id": "ev", "extra": 1}],
            "evidence": [ref.to_dict()],
        })
    with pytest.raises(BehaviorContractError, match="baseline case has unknown or missing fields"):
        BehaviorBaseline.from_dict({
            "target": "t", "revision": "r",
            "cases": [{"case_id": "c", "input_sha256": _SHA, "output_sha256": _OUT, "evidence_id": "ev", "unexpected": 1}],
            "evidence": [ref.to_dict()],
        })
    with pytest.raises(BehaviorContractError, match="observation has unknown or missing fields"):
        BehaviorObservation.from_dict({
            "case_id": "c", "input_sha256": _SHA, "output_sha256": _OUT,
            "status": "passed", "evidence_id": "ev", "unexpected": 1,
        })


def test_behavior_compare_rejects_wrong_collection_types_and_duplicate_evidence():
    baseline = _baseline()
    assert compare_behavior(baseline, object(), observation_evidence=(), verify_evidence=lambda _: True).verdict is BehaviorVerdict.INVALID
    assert compare_behavior(baseline, (), observation_evidence=object(), verify_evidence=lambda _: True).verdict is BehaviorVerdict.INVALID
    assert compare_behavior(baseline, (), observation_evidence=(object(),), verify_evidence=lambda _: True).verdict is BehaviorVerdict.INVALID
    ref = _ref("run-ev", _OUT)
    assert compare_behavior(
        baseline, (), observation_evidence=(ref, ref), verify_evidence=lambda _: True,
    ).verdict is BehaviorVerdict.INVALID


def test_capture_rejects_invalid_collections_sink_and_artifact_bounds(monkeypatch):
    import src.intelligence.capture as capture_module
    with pytest.raises(CaptureError, match="non-empty"):
        CapturedCase(" ", {}, {})
    with pytest.raises(CaptureError, match="invalid case"):
        capture_baseline(target="t", revision="r", run_id="run", cases=[object()], collected_by="test", sink=_Sink())
    with pytest.raises(CaptureError, match="duplicate case IDs"):
        capture_baseline(
            target="t", revision="r", run_id="run",
            cases=[CapturedCase("c", {}, {}), CapturedCase("c", {}, {})],
            collected_by="test", sink=_Sink(),
        )
    with pytest.raises(CaptureError, match="persistent evidence sink"):
        capture_baseline(target="t", revision="r", run_id="run", cases=[CapturedCase("c", {}, {})], collected_by="test", sink=object())
    monkeypatch.setattr(capture_module, "_MAX_ARTIFACT_BYTES", 2)
    with pytest.raises(CaptureError, match="1 MiB"):
        capture_module._canonical_bytes({"value": "long"})


def test_capture_observations_enforces_count_and_sink(monkeypatch):
    import src.intelligence.capture as capture_module
    cases = [CapturedCase("one", {}, {}), CapturedCase("two", {}, {})]
    monkeypatch.setattr(capture_module, "_MAX_CASES", 1)
    with pytest.raises(CaptureError, match="at most 1000"):
        capture_observations(
            target="t", revision="r", run_id="run", cases=cases,
            collected_by="test", sink=_Sink(),
        )
    monkeypatch.setattr(capture_module, "_MAX_CASES", 10)
    with pytest.raises(CaptureError, match="persistent evidence sink"):
        capture_observations(
            target="t", revision="r", run_id="run", cases=cases[:1],
            collected_by="test", sink=object(),
        )


def test_assurance_gate_rejects_invalid_result_and_noniterable_scope():
    assert evaluate_assurance(None, authorized_scope=("src/",), verify_evidence=lambda _: True).verdict is AssuranceVerdict.REJECTED
    result = IntelligenceResult(
        "mission", "run", "engine", "target", ("src/",), ResultStatus.COMPLETE,
        evidence=(_ref(),),
    )
    assert evaluate_assurance(result, authorized_scope=None, verify_evidence=lambda _: True).verdict is AssuranceVerdict.REJECTED
