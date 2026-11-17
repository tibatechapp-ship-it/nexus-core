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
