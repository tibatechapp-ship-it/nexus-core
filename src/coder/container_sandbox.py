"""Opt-in Docker isolation for untrusted coding-agent commands."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import tempfile
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



def _force_remove_container(
    docker: str, cidfile: Path, docker_env: dict[str, str]
) -> tuple[bool, str]:
    """Best-effort bounded cleanup after the Docker client loses control."""
    try:
        container_id = cidfile.read_text(encoding="ascii").strip()
    except OSError as exc:
        return False, f"container ID file unavailable: {type(exc).__name__}"
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        return False, "container ID file is missing or malformed"
    try:
        result = subprocess.run(
            [docker, "rm", "--force", container_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            env=docker_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"docker rm failed: {type(exc).__name__}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown Docker error").strip()
        return False, f"docker rm exited {result.returncode}: {detail[:200]}"
    return True, ""


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
    require_rootless: bool = True,
) -> dict[str, Any]:
    """Run argv in a networkless container; only workspace is writable."""
    _approved(enabled=enabled, approved=approved, image=image)
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ContainerSandboxError("command must be a non-empty argv list")
    memory_match = re.fullmatch(r"([1-9][0-9]*)(m|g)", memory)
    if memory_match is None:
        raise ContainerSandboxError("memory must be an integer followed by m or g")
    memory_value = int(memory_match.group(1))
    memory_bytes = memory_value * (
        1024**2 if memory_match.group(2) == "m" else 1024**3
    )
    if not 128 * 1024**2 <= memory_bytes <= 16 * 1024**3:
        raise ContainerSandboxError("memory must be between 128m and 16g")

    if not re.fullmatch(r"(?:[1-9][0-9]*|[0-9]+\.[0-9]+)", cpus):
        raise ContainerSandboxError("invalid CPU limit")
    if not 0.1 <= float(cpus) <= 8.0:
        raise ContainerSandboxError("cpus must be between 0.1 and 8")
    if len(command) > 128 or any(len(part) > 4096 for part in command):
        raise ContainerSandboxError("command exceeds argument limits")
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
    # Docker's selected context (including the rootless socket) is stored under
    # the user's Docker config directory. Preserve only the executable search
    # path and home directory for the Docker CLI; never forward this environment
    # to the container or inherit unrelated host credentials/configuration.
    docker_env = {
        "PATH": os.path.dirname(docker),
        "HOME": str(Path.home()),
    }
    if require_rootless:
        try:
            daemon = subprocess.run(
                [docker, "info", "--format", "{{json .SecurityOptions}}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, timeout=10, check=False,
                env=docker_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContainerSandboxError(f"rootless Docker preflight failed: {exc}") from exc
        try:
            security_options = json.loads(daemon.stdout) if daemon.returncode == 0 else []
        except json.JSONDecodeError:
            security_options = []
        rootless_enabled = isinstance(security_options, list) and any(
            isinstance(option, str) and option.casefold() == "name=rootless"
            for option in security_options
        )
        if not rootless_enabled:
            raise ContainerSandboxError(
                "rootless Docker daemon is required; refusing non-rootless execution"
            )

    container_user = "0:0" if require_rootless else "65532:65532"
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
        # Rootless Docker maps container UID 0 to the unprivileged daemon
        # owner on the host. Capabilities are still dropped and no-new-privileges
        # remains enforced; owner-only worktree files stay private to that user.
        f"--user={container_user}",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount",
        f"type=bind,src={root},dst=/workspace",
        "--workdir=/workspace",
        "--entrypoint",
        command[0],
        image,
        *command[1:],
    ]
    timeout = min(max(int(timeout), 1), MAX_TIMEOUT_S)
    with tempfile.TemporaryDirectory(prefix="nexus-container-cid-") as cid_dir:
        cidfile = Path(cid_dir) / "container.id"
        argv[1:1] = ["--cidfile", str(cidfile)]
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=docker_env,
                start_new_session=True,
            )
        except OSError as exc:
            return {
                "ok": False,
                "exit_code": None,
                "timeout": False,
                "stdout": "",
                "stderr": f"docker spawn failed: {exc}"[:200],
                "cleanup_attempted": False,
                "cleanup_ok": None,
                "cleanup_error": "",
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

        cleanup_attempted = timed_out
        cleanup_ok: bool | None = None
        cleanup_error = ""
        if timed_out:
            cleanup_ok, cleanup_error = _force_remove_container(
                docker, cidfile, docker_env
            )

        return {
            "ok": not timed_out and proc.returncode == 0,
            "exit_code": None if timed_out else proc.returncode,
            "timeout": timed_out,
            "stdout": out_buf.decode("utf-8", "replace"),
            "stderr": (
                "container timeout"
                if timed_out and cleanup_ok
                else (
                    "container timeout; cleanup unconfirmed: " + cleanup_error
                    if timed_out else err_buf.decode("utf-8", "replace")
                )
            ),
            "truncated": truncated["value"],
            "cleanup_attempted": cleanup_attempted,
            "cleanup_ok": cleanup_ok,
            "cleanup_error": cleanup_error,
        }
