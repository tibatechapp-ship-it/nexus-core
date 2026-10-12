"""
TesterAgent - Safe code execution in isolated subprocess
- Runs Python code in workspace
- Captures stdout/stderr
- Timeout protection
- Syntax pre-check
- No AI dependency - pure execution
"""
from pathlib import Path
import subprocess
import tempfile
import os
import logging
from typing import Dict, Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import EXECUTE_TIMEOUT, WORKSPACE_DIR

# Logger definition (must be before any use)
logger = logging.getLogger("tester")


try:
    from sandbox.safe_runner import safe_runner
    SANDBOX_AVAILABLE = True
except ImportError:
    SANDBOX_AVAILABLE = False
    logger.warning("SafeRunner not available — using basic subprocess")



def syntax_check(code: str) -> Dict:
    """Fast syntax check before execution."""
    try:
        compile(code, "<test>", "exec")
        return {"ok": True}
    except SyntaxError as e:
        return {
            "ok": False,
            "error": "SyntaxError line " + str(e.lineno) + ": " + str(e.msg),
            "line": e.lineno,
        }


def test_python(code: str, timeout: Optional[int] = None,
                memory_mb: int = 256) -> Dict:
    """Runs Python code in a sandboxed subprocess.

    Uses SafeRunner when available for:
    - Resource limits (CPU, memory, file size, processes)
    - Isolated temp directory
    - Clean environment
    Falls back to basic subprocess if SafeRunner is unavailable.
    """
    if not code or not code.strip():
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "empty code",
        }

    timeout = timeout or EXECUTE_TIMEOUT

    # Prefer SafeRunner
    if SANDBOX_AVAILABLE:
        result = safe_runner.run_python(
            code,
            timeout=timeout,
            memory_mb=memory_mb,
            cwd=str(WORKSPACE_DIR),
        )
        # Normalize to legacy format
        return {
            "success": result.get("success", False),
            "returncode": result.get("returncode", -1),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("error", "") or result.get("stderr", ""),
            "sandboxed": True,
            "limits": result.get("limits", {}),
        }

    # Fallback: basic subprocess
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".py",
            prefix="test_",
            dir=str(WORKSPACE_DIR),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)

        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE_DIR),
        )

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-8000:],
            "stderr": (result.stderr or "")[-4000:],
            "sandboxed": False,
        }

    except subprocess.TimeoutExpired:
        logger.warning("timeout after " + str(timeout) + "s")
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "TIMEOUT after " + str(timeout) + "s",
            "sandboxed": False,
        }
    except Exception as e:
        logger.error("execution error: " + str(e))
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "EXEC ERROR: " + str(e),
            "sandboxed": False,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


class Tester:
    def __init__(self):
        self.name = "tester"

    def run(self, code: str, timeout: Optional[int] = None) -> Dict:
        return test_python(code, timeout=timeout)

    def check(self, code: str) -> Dict:
        return syntax_check(code)


tester = Tester()
