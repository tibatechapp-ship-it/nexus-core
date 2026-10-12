#!/usr/bin/env python3
"""HiveLoop Sandbox - Code isolation and execution"""

from __future__ import annotations
import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    timeout: bool = False
    memory_exceeded: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timeout and not self.memory_exceeded


class Sandbox:
    def __init__(self, timeout: int = 10, memory_mb: int = 512):
        self.timeout = timeout
        self.memory_mb = memory_mb

    def _set_limits(self):
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (self.timeout, self.timeout + 2)
        )
        mem_bytes = self.memory_mb * 1024 * 1024
        resource.setrlimit(
            resource.RLIMIT_AS,
            (mem_bytes, mem_bytes)
        )
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (10 * 1024 * 1024, 10 * 1024 * 1024)
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def run(self, code: str, stdin: str = "") -> ExecResult:
        with tempfile.TemporaryDirectory(prefix="hive_sandbox_") as tmpdir:
            code_file = Path(tmpdir) / "solution.py"
            code_file.write_text(code, encoding="utf-8")

            t0 = time.time()
            timeout_hit = False
            memory_hit = False

            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-S", str(code_file)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=tmpdir,
                    preexec_fn=self._set_limits if os.name == "posix" else None,
                    env={"PATH": "/usr/bin:/bin", "HOME": tmpdir},
                )
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
            except subprocess.TimeoutExpired as e:
                timeout_hit = True
                if isinstance(e.stdout, bytes):
                    stdout = e.stdout.decode("utf-8", errors="replace")
                else:
                    stdout = e.stdout or ""
                stderr = "TIMEOUT"
                exit_code = -1
            except MemoryError:
                memory_hit = True
                stdout = ""
                stderr = "MEMORY_EXCEEDED"
                exit_code = -1
            except Exception as e:
                stdout = ""
                stderr = f"EXEC_ERROR: {e}"
                exit_code = -1

            duration = time.time() - t0

            return ExecResult(
                stdout=stdout[:10000],
                stderr=stderr[:5000],
                exit_code=exit_code,
                duration=round(duration, 3),
                timeout=timeout_hit,
                memory_exceeded=memory_hit,
            )


if __name__ == "__main__":
    sb = Sandbox(timeout=5, memory_mb=256)

    print("=== Test 1: Simple ===")
    r = sb.run("print('hello, world')")
    print(f"Output: {r.stdout.strip()}")
    print(f"Success: {r.success}")
    print(f"Duration: {r.duration}s")
    print()

    print("=== Test 2: Error ===")
    r = sb.run("raise ValueError('test error')")
    print(f"Exit: {r.exit_code}")
    print(f"Error: {r.stderr[:100]}")
    print(f"Success: {r.success}")
    print()

    print("=== Test 3: Timeout ===")
    r = sb.run("while True: pass")
    print(f"Timeout: {r.timeout}")
    print(f"Success: {r.success}")
    print()

    print("=== Test 4: Factorial ===")
    code = "def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)\n\nprint(factorial(5))"
    r = sb.run(code)
    print(f"Output: {r.stdout.strip()}")
    print(f"Expected: 120")
    print(f"Success: {r.success and r.stdout.strip() == '120'}")
