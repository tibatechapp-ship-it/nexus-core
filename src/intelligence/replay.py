"""Mission-authorized behavioral replay through the existing rootless container.

This adapter is the only execution-facing layer in Intelligence & Assurance.
It requires a persisted, human-approved mission record and delegates execution
to the existing container sandbox. It never falls back to a host process runner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .behavior import _required_text, digest_payload
from .capture import CapturedCase
from ..coder.container_sandbox import ContainerSandboxError, run_in_container
from .behavior import ObservationStatus

_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}$")
_MAX_CASES = 1000
_MAX_COMMAND_ARGS = 128
_MAX_ARG_LENGTH = 4096
_MAX_OUTPUT_LENGTH = 64 * 1024


class BehaviorReplayError(RuntimeError):
    """Replay was rejected or the isolated runner failed closed."""


@dataclass(frozen=True, slots=True)
class ReplayCommandCase:
    """One command and its dedicated, pre-created isolated workspace."""

    case_id: str
    argv: tuple[str, ...]
    workspace: Path
    input_payload: Any
    timeout: int = 120

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "case_id", _required_text(self.case_id, "case_id"))
        except ValueError as exc:
            raise BehaviorReplayError(str(exc)) from exc
        if not isinstance(self.argv, (tuple, list)) or not 1 <= len(self.argv) <= _MAX_COMMAND_ARGS:
            raise BehaviorReplayError("command must contain between 1 and 128 argv items")
        argv = tuple(self.argv)
        if any(
            not isinstance(part, str) or not part or len(part) > _MAX_ARG_LENGTH
            or "\x00" in part
            for part in argv
        ):
            raise BehaviorReplayError("command contains an invalid argument")
        object.__setattr__(self, "argv", argv)
        try:
            workspace = Path(self.workspace)
        except TypeError as exc:
            raise BehaviorReplayError("workspace must be a filesystem path") from exc
        if workspace.is_symlink() or not workspace.is_dir():
            raise BehaviorReplayError("each replay case requires an existing non-symlink workspace")
        object.__setattr__(self, "workspace", workspace)
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, int) or not 1 <= self.timeout <= 300:
            raise BehaviorReplayError("timeout must be an integer between 1 and 300 seconds")
        try:
            digest_payload(self.input_payload)
        except ValueError as exc:
            raise BehaviorReplayError(f"input fixture is invalid: {exc}") from exc


def _approved_image(
    mission_id: str,
    execution_policy: Mapping[str, Any],
    approval_store: Any,
) -> str:
    mission_id = _required_text(mission_id, "mission_id")
    if not isinstance(execution_policy, Mapping):
        raise BehaviorReplayError("an explicit mission execution policy is required")
    if type(execution_policy.get("schema_version")) is not int or execution_policy.get("schema_version") != 1:
        raise BehaviorReplayError("unsupported or missing execution policy schema version")
    if execution_policy.get("execution_mode") != "container":
        raise BehaviorReplayError("behavior replay refuses host process execution")
    if execution_policy.get("container_enabled") is not True:
        raise BehaviorReplayError("container execution is not explicitly enabled")
    image = execution_policy.get("container_image")
    if not isinstance(image, str) or not _IMAGE_RE.fullmatch(image):
        raise BehaviorReplayError("container image must be pinned by a lowercase sha256 digest")
    approval_id = execution_policy.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise BehaviorReplayError("persisted human approval ID is required")
    approvals_for = getattr(approval_store, "approvals_for", None)
    if not callable(approvals_for):
        raise BehaviorReplayError("approval store is unavailable")
    try:
        approvals = approvals_for(mission_id)
    except Exception as exc:
        raise BehaviorReplayError("could not retrieve mission approval records") from exc
    if not isinstance(approvals, (tuple, list)):
        raise BehaviorReplayError("approval store returned malformed records")
    matches = [
        item for item in approvals
        if getattr(item, "id", None) == approval_id
    ]
    if len(matches) != 1:
        raise BehaviorReplayError("approval ID must resolve to exactly one persisted record")
    approval = matches[0]
    if not (
        getattr(approval, "kind", None) == "run_untrusted"
        and getattr(approval, "approved", None) is True
        and isinstance(getattr(approval, "decided_by", None), str)
        and bool(approval.decided_by.strip())
        and getattr(approval, "subject", None) == image
    ):
        raise BehaviorReplayError("persisted human approval does not authorize this image")
    return image


def execute_authorized_cases(
    *,
    mission_id: str,
    execution_policy: Mapping[str, Any],
    approval_store: Any,
    cases: Sequence[ReplayCommandCase],
) -> tuple[CapturedCase, ...]:
    """Execute explicit argv cases in separately prepared rootless containers.

    The caller must prepare a distinct disposable workspace per case. Each
    workspace is mounted only into its own networkless container. All execution
    is rejected unless the mission store contains the matching human approval.
    """
    if not isinstance(cases, (tuple, list)) or not 1 <= len(cases) <= _MAX_CASES:
        raise BehaviorReplayError("replay requires between 1 and 1000 cases")
    if any(not isinstance(case, ReplayCommandCase) for case in cases):
        raise BehaviorReplayError("replay contains an invalid command case")
    if len({case.case_id for case in cases}) != len(cases):
        raise BehaviorReplayError("replay contains duplicate case IDs")
    workspace_ids = [str(case.workspace.resolve()) for case in cases]
    if len(workspace_ids) != len(set(workspace_ids)):
        raise BehaviorReplayError("each case must use a distinct disposable workspace")

    image = _approved_image(mission_id, execution_policy, approval_store)
    captured: list[CapturedCase] = []
    for case in cases:
        try:
            result = run_in_container(
                list(case.argv),
                case.workspace,
                image=image,
                enabled=True,
                approved=True,
                timeout=case.timeout,
                require_rootless=True,
            )
        except (ContainerSandboxError, OSError, ValueError) as exc:
            raise BehaviorReplayError(
                f"isolated replay failed closed for case {case.case_id}: {exc}"
            ) from exc
        required = {"ok", "exit_code", "timeout", "truncated", "stdout", "stderr"}
        if not isinstance(result, Mapping) or not required.issubset(result):
            raise BehaviorReplayError("container runner returned a malformed result")
        if (
            not isinstance(result["ok"], bool)
            or not isinstance(result["timeout"], bool)
            or not isinstance(result["truncated"], bool)
            or (result["exit_code"] is not None and (
                isinstance(result["exit_code"], bool) or not isinstance(result["exit_code"], int)
            ))
        ):
            raise BehaviorReplayError("container runner returned invalid status fields")
        stdout = result["stdout"]
        stderr = result["stderr"]
        if (
            not isinstance(stdout, str) or len(stdout.encode("utf-8")) > _MAX_OUTPUT_LENGTH
            or not isinstance(stderr, str) or len(stderr.encode("utf-8")) > _MAX_OUTPUT_LENGTH
        ):
            raise BehaviorReplayError("container runner output exceeded its bounded contract")
        exit_code = result["exit_code"]
        timed_out = result["timeout"]
        truncated = result["truncated"]
        passed = (
            result["ok"] is True and exit_code == 0
            and timed_out is False and truncated is False
        )
        output = {
            "runner": "nexus.rootless-container/v1",
            "image": image,
            "argv_sha256": digest_payload(list(case.argv)),
            "exit_code": exit_code,
            "timeout": timed_out,
            "truncated": truncated,
            "stdout": stdout,
            "stderr": stderr,
            "cleanup_attempted": result.get("cleanup_attempted", False),
            "cleanup_ok": result.get("cleanup_ok"),
            "cleanup_error": result.get("cleanup_error", ""),
        }
        captured.append(
            CapturedCase(
                case.case_id,
                case.input_payload,
                output,
                ObservationStatus.PASSED if passed else ObservationStatus.FAILED,
            )
        )
    return tuple(captured)


__all__ = [
    "BehaviorReplayError", "ReplayCommandCase", "execute_authorized_cases",
]
