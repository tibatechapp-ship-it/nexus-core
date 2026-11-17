"""Opt-in Docker isolation for untrusted coding-agent commands."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

MAX_TIMEOUT_S = 300
MAX_OUTPUT_BYTES = 64 * 1024
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}$")


class ContainerSandboxError(RuntimeError):
    """A container execution request failed closed."""


def _approved(*, enabled: bool, approved: bool, image: str) -> None:
    if not enabled or os.environ.get("NEXUS_ENABLE_CONTAINER_SANDBOX") != "1":
        raise ContainerSandboxError("container sandbox disabled; explicit opt-in required")
    if not approved:
        raise ContainerSandboxError("human approval required before command execution")
    if not _IMAGE_RE.fullmatch(image):
        raise ContainerSandboxError("image must be pinned by immutable sha256 digest")


def run_in_container(
    command: list[str],
    workspace: str | Path,
    *,
    image: str,
    enabled: bool = False,
    approved: bool = False,
    timeout: int = 120,
    memory: str = "1g",
    cpus: str = "2",
    pids_limit: int = 64,
    docker_binary: str = "docker",
) -> dict[str, Any]:
    """Run argv in a networkless container; only workspace is writable."""
    _approved(enabled=enabled, approved=approved, image=image)
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ContainerSandboxError("command must be a non-empty argv list")
    if not re.fullmatch(r"[1-9][0-9]*(?:m|g)", memory):
        raise ContainerSandboxError("invalid memory limit")
    if not re.fullmatch(r"(?:[1-9][0-9]*|[0-9]+\.[0-9]+)", cpus):
        raise ContainerSandboxError("invalid CPU limit")
    if not 1 <= pids_limit <= 256:
        raise ContainerSandboxError("pids_limit must be between 1 and 256")

    requested_workspace = Path(workspace)
    root = requested_workspace.resolve(strict=True)
    if not root.is_dir() or requested_workspace.is_symlink():
        raise ContainerSandboxError("workspace must be an existing directory")
    if "," in str(root):
        raise ContainerSandboxError("workspace paths containing commas are unsupported")

    docker = shutil.which(docker_binary)
    if docker is None:
        raise ContainerSandboxError("Docker CLI not found")

    argv = [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        f"--pids-limit={pids_limit}",
        f"--memory={memory}",
        f"--cpus={cpus}",
        "--user=65532:65532",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount",
        f"type=bind,src={root},dst=/workspace,rw",
        "--workdir=/workspace",
        "--entrypoint",
        command[0],
        image,
        *command[1:],
    ]
    timeout = min(max(int(timeout), 1), MAX_TIMEOUT_S)
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.path.dirname(docker)},
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": None,
            "timeout": False,
            "stdout": "",
            "stderr": f"docker spawn failed: {exc}"[:200],
        }

    out_buf = bytearray()
    err_buf = bytearray()
    truncated = {"value": False}

    def drain(pipe: Any, sink: bytearray) -> None:
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                remaining = MAX_OUTPUT_BYTES - len(sink)
                if remaining > 0:
                    sink.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated["value"] = True
        finally:
            pipe.close()

    threads = [
        threading.Thread(target=drain, args=(proc.stdout, out_buf), daemon=True),
        threading.Thread(target=drain, args=(proc.stderr, err_buf), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        proc.wait()

    for thread in threads:
        thread.join(timeout=5)

    return {
        "ok": not timed_out and proc.returncode == 0,
        "exit_code": None if timed_out else proc.returncode,
        "timeout": timed_out,
        "stdout": out_buf.decode("utf-8", "replace"),
        "stderr": "container timeout" if timed_out else err_buf.decode("utf-8", "replace"),
        "truncated": truncated["value"],
    }
