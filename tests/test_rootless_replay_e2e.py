"""Opt-in real Rootless Docker integration test for behavior replay.

This test is skipped in the normal unit suite. The dedicated GitHub Actions
workflow provisions a rootless daemon and preloads the pinned runner image.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.intelligence.behavior import ObservationStatus
from src.intelligence.replay import ReplayCommandCase, execute_authorized_cases

pytestmark = pytest.mark.skipif(
    os.environ.get("NEXUS_RUN_ROOTLESS_E2E") != "1",
    reason="requires the dedicated Rootless Docker E2E workflow",
)


def test_approved_behavior_replay_runs_in_real_rootless_container(tmp_path: Path) -> None:
    image = os.environ.get("NEXUS_E2E_CONTAINER_IMAGE", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}", image):
        pytest.fail("NEXUS_E2E_CONTAINER_IMAGE must be an immutable sha256 image reference")

    workspace = tmp_path / "case"
    workspace.mkdir(mode=0o700)
    fixture_dir = workspace / ".nexus-behavior"
    fixture_dir.mkdir(mode=0o700)
    fixture = fixture_dir / "input.json"
    fixture.write_text(json.dumps({"marker": "nexus-rootless-e2e-ok"}), encoding="utf-8")
    fixture.chmod(0o600)

    probe = (
        "import json,pathlib,socket,sys\n"
        "data=json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "sock=socket.socket();sock.settimeout(1)\n"
        "network_result=sock.connect_ex(('1.1.1.1',53));sock.close()\n"
        "assert network_result != 0, 'container unexpectedly reached the network'\n"
        "target=pathlib.Path('/etc/nexus-rootless-e2e-write-probe')\n"
        "try:\n"
        "    target.write_text('must-not-write')\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('container root filesystem is writable')\n"
        "print(data['marker'])\n"
    )
    case = ReplayCommandCase(
        case_id="rootless-isolation-probe",
        argv=("python", "-c", probe, "/workspace/.nexus-behavior/input.json"),
        workspace=workspace,
        input_payload={"marker": "nexus-rootless-e2e-ok"},
        timeout=30,
    )

    class ApprovalStore:
        def approvals_for(self, mission_id: str):
            assert mission_id == "mission-rootless-e2e"
            return [SimpleNamespace(
                id="approval-rootless-e2e",
                kind="run_untrusted",
                approved=True,
                decided_by="github-actions-e2e-operator",
                subject=image,
            )]

    captured = execute_authorized_cases(
        mission_id="mission-rootless-e2e",
        execution_policy={
            "schema_version": 1,
            "execution_mode": "container",
            "container_enabled": True,
            "container_image": image,
            "approval_id": "approval-rootless-e2e",
        },
        approval_store=ApprovalStore(),
        cases=[case],
    )

    assert len(captured) == 1
    if captured[0].status is not ObservationStatus.PASSED:
        output = captured[0].output_payload
        pytest.fail(
            "real rootless replay failed: "
            f"exit_code={output.get('exit_code')!r}, "
            f"timeout={output.get('timeout')!r}, "
            f"stderr={output.get('stderr')!r}, "
            f"stdout={output.get('stdout')!r}"
        )
    assert captured[0].output_payload["runner"] == "nexus.rootless-container/v1"
    assert captured[0].output_payload["image"] == image
    assert captured[0].output_payload["stdout"].strip() == "nexus-rootless-e2e-ok"
    assert captured[0].output_payload["timeout"] is False
    assert captured[0].output_payload["truncated"] is False
