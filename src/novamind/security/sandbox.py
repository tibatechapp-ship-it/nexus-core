"""Sandbox — Isolated Execution."""
import subprocess
import resource
import tempfile
from pathlib import Path


class Sandbox:
    def __init__(self, timeout=30, max_memory_mb=256):
        self.timeout = timeout
        self.max_memory = max_memory_mb * 1024 * 1024

    def run_python(self, code, stdin=""):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="/tmp"
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            def preexec():
                resource.setrlimit(
                    resource.RLIMIT_AS,
                    (self.max_memory, self.max_memory)
                )
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (self.timeout, self.timeout)
                )

            result = subprocess.run(
                ["python3", script_path],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                preexec_fn=preexec,
                cwd="/tmp",
                env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
            )

            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout[:10000],
                "stderr": result.stderr[:5000],
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            Path(script_path).unlink(missing_ok=True)
