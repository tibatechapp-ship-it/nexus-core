"""Explicit, auditable behavior replay for completed missions.

Restores a verified mission checkpoint, creates one disposable workspace per
test case, requires persisted mission approval, stores evidence, compares
observations, and appends audit events. Never invoked automatically.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from src.org.recovery_context import fingerprint_directory, restore_mission_context
from .behavior import (
    BehaviorBaseline, BehaviorComparison, _required_text, compare_behavior,
    digest_payload,
)
from .capture import EvidenceSink, capture_observations
from .replay import ReplayCommandCase, execute_authorized_cases

_MAX_CASES = 1000
_MAX_SNAPSHOT_FILES = 100_000
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024 * 1024
_IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next",
    "dist", "build", "target",
}
_SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".npmrc", ".netrc",
    ".pypirc", "id_rsa", "id_ed25519", "credentials.json", "token.json",
}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class MissionBehaviorError(RuntimeError):
    """Mission replay could not be safely prepared or completed."""


@dataclass(frozen=True, slots=True)
class BehaviorCaseSpec:
    """Command declaration; the service assigns a fresh isolated workspace."""

    case_id: str
    argv: tuple[str, ...]
    input_payload: Any
    timeout: int = 120

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "case_id", _required_text(self.case_id, "case_id"))
        except ValueError as exc:
            raise MissionBehaviorError(str(exc)) from exc
        if not isinstance(self.argv, (tuple, list)) or not 1 <= len(self.argv) <= 128:
            raise MissionBehaviorError("command must contain between 1 and 128 argv items")
        argv = tuple(self.argv)
        if any(
            not isinstance(part, str) or not part or len(part) > 4096 or "\x00" in part
            for part in argv
        ):
            raise MissionBehaviorError("command contains an invalid argument")
        if sum(part == "{behavior_input}" for part in argv) != 1:
            raise MissionBehaviorError(
                "command must contain exactly one {behavior_input} argument"
            )
        object.__setattr__(self, "argv", argv)
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, int) or not 1 <= self.timeout <= 300:
            raise MissionBehaviorError("timeout must be an integer between 1 and 300 seconds")
        try:
            digest_payload(self.input_payload)
        except ValueError as exc:
            raise MissionBehaviorError(f"input fixture is invalid: {exc}") from exc


@dataclass(frozen=True, slots=True)
class MissionBehaviorReplayResult:
    mission_id: str
    baseline_revision: str
    candidate_revision: str
    comparison: BehaviorComparison
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "baseline_revision": self.baseline_revision,
            "candidate_revision": self.candidate_revision,
            "comparison": self.comparison.to_dict(),
            "evidence_ids": list(self.evidence_ids),
        }


def _append_behavior_report(
        mission: Any, result: MissionBehaviorReplayResult, run_id: str
) -> bool:
    """Atomically append a bounded replay verdict to the mission's final report."""
    report_value = getattr(mission, "report_path", "")
    if not isinstance(report_value, str) or not report_value.strip():
        return False
    report = Path(report_value)
    if report.is_symlink() or not report.is_file():
        raise MissionBehaviorError("mission final report is missing or is not a regular file")
    report = report.resolve(strict=True)
    if report.stat().st_size > 2 * 1024 * 1024:
        raise MissionBehaviorError("mission final report exceeds the 2 MiB update limit")

    comparison = result.comparison
    payload = {
        "schema": "nexus.behavior-report/v1",
        "run_id": run_id,
        "mission_id": result.mission_id,
        "baseline_revision": result.baseline_revision,
        "candidate_revision": result.candidate_revision,
        "verdict": comparison.verdict.value,
        "matched_case_ids": list(comparison.matched_case_ids),
        "missing_case_ids": list(comparison.missing_case_ids),
        "changed_case_ids": list(comparison.changed_case_ids),
        "unexpected_case_ids": list(comparison.unexpected_case_ids),
        "evidence_ids": list(result.evidence_ids),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > 128 * 1024:
        raise MissionBehaviorError("behavior report section exceeds 128 KiB")
    marker = f"<!-- nexus-behavior-run:{digest_payload(run_id)} -->"
    original = report.read_text(encoding="utf-8")
    if marker in original:
        raise MissionBehaviorError("behavior replay run is already present in the final report")
    section = (
        f"\n\n## التحقق السلوكي\n\n{marker}\n"
        f"\n```json\n{encoded}\n```\n"
    )
    updated = original.rstrip() + section
    fd, temporary_name = tempfile.mkstemp(
        prefix=".nexus-report-", suffix=".tmp", dir=str(report.parent)
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, report)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return True


def _is_sensitive_name(name: str) -> bool:
    lowered = name.casefold()
    if lowered in _SENSITIVE_NAMES:
        return True
    if lowered.startswith(".env.") and lowered not in {
        ".env.example", ".env.template", ".env.sample"
    }:
        return True
    return Path(lowered).suffix in _SENSITIVE_SUFFIXES


def _copy_verified_snapshot(source: Path, destination: Path) -> None:
    """Copy a verified worktree without Git metadata, links, or credential files."""
    if source.is_symlink():
        raise MissionBehaviorError("mission worktree root must not be a symlink")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise MissionBehaviorError("verified mission worktree is not a real directory")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    file_count = 0
    byte_count = 0
    for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        target_dir = destination / relative
        target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in list(dirs):
            item = current_path / name
            if item.is_symlink():
                raise MissionBehaviorError("symlink directory in mission worktree is not replayable")
            if name in _IGNORED_DIRS:
                dirs.remove(name)
        for name in sorted(files):
            item = current_path / name
            if item.is_symlink():
                raise MissionBehaviorError("symlink file in mission worktree is not replayable")
            if not item.is_file():
                raise MissionBehaviorError("non-regular file in mission worktree is not replayable")
            if _is_sensitive_name(name):
                raise MissionBehaviorError(
                    f"credential-like file must be removed before replay: {name}"
                )
            stat = item.stat()
            file_count += 1
            byte_count += stat.st_size
            if file_count > _MAX_SNAPSHOT_FILES or byte_count > _MAX_SNAPSHOT_BYTES:
                raise MissionBehaviorError("mission snapshot exceeds replay copy limits")
            target = target_dir / name
            shutil.copy2(item, target, follow_symlinks=False)
            os.chmod(target, 0o600)
    for current, _dirs, _files in os.walk(destination, topdown=False):
        os.chmod(current, 0o700)


def _stage_behavior_input(workspace: Path, payload: Any) -> str:
    """Write a canonical, bounded input fixture into the disposable workspace."""
    directory = workspace / ".nexus-behavior"
    directory.mkdir(mode=0o700, exist_ok=False)
    try:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise MissionBehaviorError("behavior input fixture is not canonical JSON") from exc
    if len(encoded) > 1024 * 1024:
        raise MissionBehaviorError("behavior input fixture exceeds the 1 MiB limit")
    fixture = directory / "input.json"
    with fixture.open("xb") as stream:
        stream.write(encoded)
    os.chmod(fixture, 0o600)
    return "/workspace/.nexus-behavior/input.json"


def run_mission_behavior_replay(
    *,
    store: Any,
    mission_id: str,
    state_root: str | Path,
    baseline: BehaviorBaseline,
    cases: Sequence[BehaviorCaseSpec],
    run_id: str,
    collected_by: str,
    evidence_sink: EvidenceSink,
    verify_evidence: Callable[[Any], bool],
) -> MissionBehaviorReplayResult:
    """Run an explicitly requested, approved replay against a completed mission.

    The baseline target must be bound to mission:<mission_id>. The latest
    checkpoint is restored and verified before any workspace is copied.
    Temporary case workspaces are deleted after comparison, including on error.
    """
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise MissionBehaviorError("mission ID is required")
    mission_id = mission_id.strip()
    if not isinstance(baseline, BehaviorBaseline):
        raise MissionBehaviorError("a valid behavior baseline is required")
    if baseline.target != f"mission:{mission_id}":
        raise MissionBehaviorError("baseline target is not bound to this mission")
    if not isinstance(cases, (tuple, list)) or not 1 <= len(cases) <= _MAX_CASES:
        raise MissionBehaviorError("replay requires between 1 and 1000 cases")
    if any(not isinstance(case, BehaviorCaseSpec) for case in cases):
        raise MissionBehaviorError("replay contains an invalid case declaration")
    if len({case.case_id for case in cases}) != len(cases):
        raise MissionBehaviorError("replay contains duplicate case IDs")
    if not callable(verify_evidence):
        raise MissionBehaviorError("independent evidence verifier is required")
    try:
        _required_text(run_id, "run_id")
        _required_text(collected_by, "collected_by")
    except ValueError as exc:
        raise MissionBehaviorError(str(exc)) from exc
    if not callable(getattr(evidence_sink, "put", None)):
        raise MissionBehaviorError("immutable evidence sink is required")

    mission = store.mission_get(mission_id)
    if mission is None or mission.status != "done":
        store.audit("behavior.replay.failed", mission_id, {
            "error_type": "MissionBehaviorError",
            "error": "behavior replay is allowed only for an existing completed mission",
        })
        raise MissionBehaviorError("behavior replay is allowed only for an existing completed mission")
    state_path = Path(state_root).expanduser().resolve(strict=True)
    repo_path = Path(mission.repo_path).expanduser().resolve(strict=True)
    if (
        state_path == repo_path
        or repo_path in state_path.parents
        or state_path in repo_path.parents
    ):
        raise MissionBehaviorError("mission state root must be outside the target repository")

    store.audit("behavior.replay.requested", mission_id, {
        "baseline_revision": baseline.revision,
        "case_count": len(cases),
        "execution_mode": "container",
    })
    try:
        # Verify the baseline before executing any candidate code. The
        # comparator repeats verification when producing the final verdict.
        for reference in baseline.evidence:
            try:
                baseline_verified = verify_evidence(reference)
            except Exception:
                baseline_verified = False
            if baseline_verified is not True:
                raise MissionBehaviorError(
                    "baseline evidence failed independent verification"
                )
        context = restore_mission_context(
            store, mission_id, state_path, expected_repo_root=repo_path
        )
        if context.worktree is None:
            raise MissionBehaviorError("completed mission has no verified worktree checkpoint")
        checkpoint_mission = context.mission
        if (
            getattr(checkpoint_mission, "status", None) != "running"
            or getattr(checkpoint_mission, "phase", None) != mission.phase
        ):
            raise MissionBehaviorError(
                "latest checkpoint is not the final pre-completion mission state"
            )
        policy = context.execution_policy
        candidate_revision = str(
            fingerprint_directory(context.worktree.root, include_git=False)["digest"]
        )
        with tempfile.TemporaryDirectory(
            prefix=f"behavior-{digest_payload(mission_id)[:16]}-", dir=state_path
        ) as temporary_root:
            root = Path(temporary_root)
            os.chmod(root, 0o700)
            replay_cases: list[ReplayCommandCase] = []
            for index, case in enumerate(cases):
                workspace = root / f"case-{index:04d}"
                _copy_verified_snapshot(Path(context.worktree.root), workspace)
                fixture_path = _stage_behavior_input(workspace, case.input_payload)
                command = tuple(
                    fixture_path if part == "{behavior_input}" else part
                    for part in case.argv
                )
                replay_cases.append(ReplayCommandCase(
                    case_id=case.case_id, argv=command,
                    workspace=workspace, input_payload=case.input_payload,
                    timeout=case.timeout,
                ))
            captured = execute_authorized_cases(
                mission_id=mission_id, execution_policy=policy,
                approval_store=store, cases=replay_cases,
            )
            observations, references = capture_observations(
                target=baseline.target, revision=candidate_revision,
                run_id=run_id, cases=captured, collected_by=collected_by,
                sink=evidence_sink,
            )
            comparison = compare_behavior(
                baseline, observations, observation_evidence=references,
                verify_evidence=verify_evidence,
            )
        result = MissionBehaviorReplayResult(
            mission_id=mission_id, baseline_revision=baseline.revision,
            candidate_revision=candidate_revision, comparison=comparison,
            evidence_ids=tuple(item.evidence_id for item in references),
        )
        report_persisted = _append_behavior_report(mission, result, run_id)
        if report_persisted:
            store.audit("behavior.replay.report_persisted", mission_id, {
                "report_path": str(mission.report_path),
                "verdict": comparison.verdict.value,
                "run_id": run_id,
            })
        else:
            store.audit("behavior.replay.report_unavailable", mission_id, {
                "reason": "legacy mission has no persisted report_path",
                "run_id": run_id,
            })
        store.audit("behavior.replay.completed", mission_id, {
            "baseline_revision": result.baseline_revision,
            "candidate_revision": result.candidate_revision,
            "verdict": comparison.verdict.value,
            "matched": len(comparison.matched_case_ids),
            "missing": len(comparison.missing_case_ids),
            "changed": len(comparison.changed_case_ids),
            "unexpected": len(comparison.unexpected_case_ids),
            "matched_case_ids": list(comparison.matched_case_ids),
            "missing_case_ids": list(comparison.missing_case_ids),
            "changed_case_ids": list(comparison.changed_case_ids),
            "unexpected_case_ids": list(comparison.unexpected_case_ids),
            "evidence_ids": list(result.evidence_ids),
            "result_sha256": digest_payload(result.to_dict()),
        })
        return result
    except Exception as exc:
        store.audit("behavior.replay.failed", mission_id, {
            "error_type": type(exc).__name__, "error": str(exc)[:500],
        })
        if isinstance(exc, MissionBehaviorError):
            raise
        raise MissionBehaviorError(
            f"mission behavior replay failed closed: {type(exc).__name__}"
        ) from exc


__all__ = [
    "BehaviorCaseSpec", "MissionBehaviorError", "MissionBehaviorReplayResult",
    "run_mission_behavior_replay",
]
