"""Container-mode guard tests for the coder execution boundary."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.coder.container_sandbox import ContainerSandboxError, run_in_container

IMAGE = "registry.example/runner@sha256:" + "b" * 64


def test_container_refuses_non_rootless_daemon(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    monkeypatch.setattr("src.coder.container_sandbox.shutil.which", lambda _: "/usr/bin/docker")

    def fake_run(*args, **kwargs):
        assert kwargs["env"]["HOME"] == str(Path.home())
        assert set(kwargs["env"]) == {"PATH", "HOME"}
        return subprocess.CompletedProcess(args[0], 0, stdout='["name=seccomp"]', stderr="")

    monkeypatch.setattr("src.coder.container_sandbox.subprocess.run", fake_run)
    with pytest.raises(ContainerSandboxError, match="rootless Docker"):
        run_in_container(
            ["python", "-V"], tmp_path, image=IMAGE,
            enabled=True, approved=True,
        )


def test_container_accepts_rootless_security_option(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NEXUS_ENABLE_CONTAINER_SANDBOX", "1")
    monkeypatch.setattr("src.coder.container_sandbox.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        "src.coder.container_sandbox.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout='["name=rootless","name=seccomp"]', stderr=""
        ),
    )
    captured = {}

    class Proc:
        pid = 43210
        stdout = None
        stderr = None
        returncode = 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        proc = Proc()
        proc.stdout = __import__("io").BytesIO(b"ok")
        proc.stderr = __import__("io").BytesIO(b"")
        return proc

    monkeypatch.setattr("src.coder.container_sandbox.subprocess.Popen", fake_popen)
    result = run_in_container(
        ["python", "-V"], tmp_path, image=IMAGE,
        enabled=True, approved=True,
    )
    assert result["ok"] is True
    assert set(captured["env"]) == {"PATH", "HOME"}
    assert captured["env"]["HOME"] == str(Path.home())
    assert "NEXUS_ENABLE_CONTAINER_SANDBOX" not in captured["env"]
    assert "--network=none" in captured["argv"]
    assert "--read-only" in captured["argv"]
    assert "--cap-drop=ALL" in captured["argv"]
    assert "--user=0:0" in captured["argv"]
