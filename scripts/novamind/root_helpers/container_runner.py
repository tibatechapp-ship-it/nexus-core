"""
Container Runner — Docker-based sandbox for untrusted code.

Falls back to subprocess (SafeRunner) if Docker unavailable.

Usage:
    from sandbox.container_runner import ContainerRunner
    runner = ContainerRunner()
    result = runner.run("print('hello')", timeout=10)
"""
import os
import shutil
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("sandbox.container_runner")

# Docker image
DEFAULT_IMAGE = "python:3.12-slim"
DOCKER_TIMEOUT = 60


def is_docker_available() -> bool:
    """Check if Docker is available."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


class ContainerRunner:
    """Runs untrusted code in a Docker container."""

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        memory_limit: str = "256m",
        cpu_limit: str = "0.5",
        network: str = "none",
    ):
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network = network
        self.docker_available = is_docker_available()
        self._fallback = None

        if not self.docker_available:
            logger.warning(
                "Docker not available — using SafeRunner fallback"
            )
            try:
                from sandbox.safe_runner import safe_runner
                self._fallback = safe_runner
            except ImportError:
                logger.error("SafeRunner also unavailable!")

    def run(
        self,
        code: str,
        timeout: int = 10,
        memory_mb: int = 256,
    ) -> Dict:
        """Run code in a container (or fallback)."""
        if not code or not code.strip():
            return {"success": False, "error": "empty code"}

        # Fallback
        if not self.docker_available:
            return self._run_fallback(code, timeout, memory_mb)

        # Docker
        return self._run_docker(code, timeout)

    def _run_docker(self, code: str, timeout: int) -> Dict:
        """Run code in Docker container."""
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="nova_docker_")
            script = os.path.join(tmp_dir, "script.py")
            Path(script).write_text(code, encoding="utf-8")

            cmd = [
                "docker", "run", "--rm",
                "--network", self.network,
                "--memory", self.memory_limit,
                "--cpus", self.cpu_limit,
                "--pids-limit", "50",
                "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "-v", f"{script}:/code/script.py:ro",
                "-w", "/tmp",
                self.image,
                "python", "/code/script.py",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + DOCKER_TIMEOUT,
            )

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[:5000],
                "stderr": (result.stderr or "")[:2000],
                "sandboxed": "docker",
                "limits": {
                    "timeout": timeout,
                    "memory": self.memory_limit,
                    "cpu": self.cpu_limit,
                    "network": self.network,
                },
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"container timeout after {timeout}s",
                "sandboxed": "docker",
            }
        except Exception as e:
            logger.exception("docker run failed")
            return {"success": False, "error": str(e)[:200], "sandboxed": "docker"}
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_fallback(self, code: str, timeout: int, memory_mb: int) -> Dict:
        """Fallback to SafeRunner."""
        if self._fallback is None:
            return {
                "success": False,
                "error": "no sandbox available (docker + saferunner both missing)",
                "sandboxed": "none",
            }
        result = self._fallback.run_python(code, timeout=timeout, memory_mb=memory_mb)
        result["sandboxed"] = "subprocess-fallback"
        return result


__all__ = ["ContainerRunner", "is_docker_available"]


if __name__ == "__main__":
    import json
    runner = ContainerRunner()
    print(f"Docker available: {runner.docker_available}")
    print()
    result = runner.run("print('Hello from sandbox!')", timeout=10)
    print(json.dumps(result, indent=2))
