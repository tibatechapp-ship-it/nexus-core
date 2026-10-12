"""Shell command execution tools with safety"""
from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.base import Tool, ToolResult, registry


SAFE_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "echo", "pwd", "date", "whoami", "uname", "df", "du",
    "python3", "pip3", "git", "curl", "wget",
    "mkdir", "touch", "cp", "mv", "rm", "chmod",
    "sort", "uniq", "awk", "sed", "tr", "cut", "xargs",
    "which", "file", "stat", "dif", "tar", "gzip", "gunzip",
}

BLOCKED_PATTERNS = [
    "rm -rf /", "mkfs", "dd if=", "> /dev/sda",
    "shutdown", "reboot", "halt", "init 0",
]


class RunCommandTool(Tool):
    name = "run_command"
    description = "Execute a shell command (whitelisted)."
    danger_level = "dangerous"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
                "cwd": {"type": "string", "default": os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))},
            },
            "required": ["command"],
        }

    def run(self, command, timeout=30, cwd=os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent))):
        for pattern in BLOCKED_PATTERNS:
            if pattern in command:
                return ToolResult(ok=False, error="blocked: " + pattern)

        try:
            parts = shlex.split(command)
        except ValueError as e:
            return ToolResult(ok=False, error="parse: " + str(e))

        if not parts:
            return ToolResult(ok=False, error="empty command")

        base = parts[0]
        if base not in SAFE_COMMANDS:
            return ToolResult(ok=False, error="not allowed: " + base)

        try:
            result = subprocess.run(shlex.split(command) if isinstance(command, str) else command, shell=False, capture_output=True,
                text=True, timeout=timeout, cwd=cwd,
            )
            return ToolResult(ok=True, data={
                "command": command,
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[-4000:],
                "stderr": (result.stderr or "")[-2000:],
                "success": result.returncode == 0,
            })
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error="timeout " + str(timeout) + "s")
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])


class RunPythonTool(Tool):
    name = "run_python"
    description = "Run Python code and return output."
    danger_level = "warn"

    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer", "default": 20},
            },
            "required": ["code"],
        }

    def run(self, code, timeout=20):
        if not code or not code.strip():
            return ToolResult(ok=False, error="empty code")

        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(
                suffix=".py", prefix="tool_",
                dir=f"{os.environ.get('NOVAMIND_HOME', str(Path(__file__).resolve().parent.parent))}/workspace",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)

            result = subprocess.run(
                ["python3", tmp],
                capture_output=True, text=True, timeout=timeout,
                cwd=f"{os.environ.get('NOVAMIND_HOME', str(Path(__file__).resolve().parent.parent))}/workspace",
            )
            return ToolResult(ok=True, data={
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[-4000:],
                "stderr": (result.stderr or "")[-2000:],
                "success": result.returncode == 0,
            })
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error="timeout " + str(timeout) + "s")
        except Exception as e:
            return ToolResult(ok=False, error=str(e)[:200])
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass


registry.register(RunCommandTool())
registry.register(RunPythonTool())
