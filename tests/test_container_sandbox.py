"""Fail-closed tests for Docker execution gating."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.coder.container_sandbox import (
    ContainerSandboxError,
    _approved,
    run_in_container,
)

IMAGE = "registry.example/nexus-runner@sha256:" + "a" * 64


def test_requires_opt_in_and_human_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_ENABLE_CONTAINER_SANDBOX", raising=False)
    with pytest.raises(ContainerSandboxError, match="disabled"):
        _approved(enabled=True, approved=True, image=IMAGE)

    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    with pytest.raises(ContainerSandboxError, match="human approval"):
        _approved(enabled=True, approved=False, image=IMAGE)


def test_rejects_mutable_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    with pytest.raises(ContainerSandboxError, match="sha256"):
        _approved(enabled=True, approved=True, image="python:3.13")


def test_bounds_are_checked_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    with pytest.raises(ContainerSandboxError, match="pids_limit"):
        run_in_container(
            ["python", "-V"],
            tmp_path,
            image=IMAGE,
            enabled=True,
            approved=True,
            pids_limit=999,
        )


@pytest.mark.parametrize("memory", ["64m", "32g", "0m", "invalid"])
def test_memory_limits_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, memory: str
) -> None:
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    with pytest.raises(ContainerSandboxError):
        run_in_container(
            ["python", "-V"],
            tmp_path,
            image=IMAGE,
            enabled=True,
            approved=True,
            memory=memory,
        )


@pytest.mark.parametrize("cpus", ["0.01", "9", "invalid"])
def test_cpu_limits_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cpus: str
) -> None:
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    with pytest.raises(ContainerSandboxError):
        run_in_container(
            ["python", "-V"],
            tmp_path,
            image=IMAGE,
            enabled=True,
            approved=True,
            cpus=cpus,
        )

def test_workspace_must_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    with pytest.raises(FileNotFoundError):
        run_in_container(
            ["python", "-V"],
            tmp_path / "missing",
            image=IMAGE,
            enabled=True,
            approved=True,
        )



def _timeout_runner(
    monkeypatch: pytest.MonkeyPatch,
    cidfile_contents: str | None = "a" * 64,
    cleanup_returncode: int = 0,
) -> tuple[list[tuple[str, list[str]]], type]:
    import io
    import os
    import subprocess
    import src.coder.container_sandbox as sandbox

    calls: list[tuple[str, list[str]]] = []
    processes: list[FakeProcess] = []

    class FakeProcess:
        pid = 4242
        stdout = io.BytesIO(b"")
        stderr = io.BytesIO(b"")
        returncode = None

        def __init__(self, command: list[str], **kwargs: object) -> None:
            calls.append(("popen", command))
            processes.append(self)
            cid_path = Path(command[command.index("--cidfile") + 1])
            if cidfile_contents is not None:
                cid_path.write_text(cidfile_contents, encoding="ascii")

        def wait(self, timeout: float | None = None) -> int | None:
            if self.returncode is None:
                raise subprocess.TimeoutExpired("docker run", timeout)
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(("run", command))
        return subprocess.CompletedProcess(command, cleanup_returncode, "", "cleanup failed")

    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(sandbox.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        sandbox.os, "killpg",
        lambda pid, sig: setattr(processes[0], "returncode", -9),
    )
    return calls, FakeProcess


def test_timeout_force_removes_container_by_cidfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _ = _timeout_runner(monkeypatch)
    result = run_in_container(
        ["python", "-c", "pass"], tmp_path, image=IMAGE,
        enabled=True, approved=True, timeout=1, require_rootless=False,
    )
    assert result["timeout"] is True
    assert result["cleanup_attempted"] is True
    assert result["cleanup_ok"] is True
    docker_run = next(command for kind, command in calls if kind == "popen")
    assert docker_run[1] == "run"
    assert docker_run[2] == "--cidfile"
    cleanup = next(command for kind, command in calls if kind == "run")
    assert cleanup[:3] == ["/usr/bin/docker", "rm", "--force"]
    assert cleanup[3] == "a" * 64


def test_timeout_reports_unconfirmed_cleanup_when_docker_rm_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _ = _timeout_runner(monkeypatch, cleanup_returncode=1)
    result = run_in_container(
        ["python", "-c", "pass"], tmp_path, image=IMAGE,
        enabled=True, approved=True, timeout=1, require_rootless=False,
    )
    assert result["timeout"] is True
    assert result["cleanup_attempted"] is True
    assert result["cleanup_ok"] is False
    assert "cleanup failed" in result["cleanup_error"]


def test_timeout_reports_missing_container_id_without_unbounded_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _ = _timeout_runner(monkeypatch, cidfile_contents=None)
    result = run_in_container(
        ["python", "-c", "pass"], tmp_path, image=IMAGE,
        enabled=True, approved=True, timeout=1, require_rootless=False,
    )
    assert result["timeout"] is True
    assert result["cleanup_ok"] is False
    assert "ID file unavailable" in result["cleanup_error"]
    assert not any(kind == "run" for kind, _ in calls)
