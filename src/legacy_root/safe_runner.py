"""
SafeRunner - Sandboxed code execution (Alpine-compatible)
- Resource limits (CPU, memory, file size, processes)
- Timeout protection
- Temp directory isolation
- Graceful fallback on musl/Alpine
"""
import os
import sys
import subprocess
import tempfile
import logging
import shutil
from pathlib import Path
from typing import Dict, Optional

try:
    import resource
    RESOURCE_AVAILABLE = True
except ImportError:
    resource = None
    RESOURCE_AVAILABLE = False

logger = logging.getLogger("sandbox.safe_runner")


class SafeRunner:
    def __init__(self, workspace: str = f"{os.environ.get('NOVAMIND_HOME', str(Path(__file__).resolve().parent.parent))}/workspace"):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _set_limits(self, timeout: int, memory_mb: int):
        """Sets resource limits. Gracefully handles unsupported limits on musl/Alpine."""
        if not RESOURCE_AVAILABLE:
            return

        limits_to_set = [
            ("RLIMIT_AS", memory_mb * 1024 * 1024),
            ("RLIMIT_CPU", (timeout, timeout + 5)),
            ("RLIMIT_FSIZE", (10 * 1024 * 1024,) * 2),
            ("RLIMIT_NPROC", (50, 50)),
            ("RLIMIT_NOFILE", (100, 100)),
            ("RLIMIT_CORE", (0, 0)),
        ]

        for name, val in limits_to_set:
            try:
                const = getattr(resource, name, None)
                if const is None:
                    continue
                if isinstance(val, tuple):
                    resource.setrlimit(const, val)
                else:
                    resource.setrlimit(const, (val, val))
            except (ValueError, OSError, AttributeError) as e:
                logger.debug(f"limit {name} skipped: {e}")

    def run_python(self, code: str,
                   timeout: int = 15,
                   memory_mb: int = 256,
                   cwd: Optional[str] = None) -> Dict:
        """Runs Python code in isolated subprocess."""
        if not code or not code.strip():
            return {"success": False, "error": "empty code"}

        work_dir = cwd or str(self.workspace)

        try:
            tmp_dir = tempfile.mkdtemp(prefix="nova_sandbox_", dir=work_dir)
        except Exception as e:
            return {"success": False, "error": f"tmpdir: {e}"}

        tmp_file = os.path.join(tmp_dir, "script.py")

        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(code)

            result = subprocess.run(
                ["python3", tmp_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp_dir,
                preexec_fn=lambda: self._set_limits(timeout, memory_mb),
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONIOENCODING": "utf-8",
                    "HOME": tmp_dir,
                    "TMPDIR": tmp_dir,
                },
            )

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[:5000],
                "stderr": (result.stderr or "")[:2000],
                "limits": {"timeout": timeout, "memory_mb": memory_mb},
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"timeout after {timeout}s",
                "limits": {"timeout": timeout, "memory_mb": memory_mb},
            }
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}
        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


safe_runner = SafeRunner()
