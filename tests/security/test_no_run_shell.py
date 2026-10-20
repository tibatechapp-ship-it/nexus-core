"""Guard: run_shell must never return. RCE via shell=True + startswith."""
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]


def test_run_shell_not_in_src():
    """No file in src/ defines or calls run_shell."""
    src = REPO / "src"
    if not src.exists():
        pytest.skip("src/ not present")
    result = subprocess.run(
        ["grep", "-rn", "run_shell", str(src), "--include=*.py"],
        capture_output=True, text=True,
    )
    hits = [
        line for line in result.stdout.splitlines()
        if "run_shell" in line and not line.strip().startswith("#")
    ]
    assert not hits, (
        "run_shell reappeared — it is unsafe (RCE via shell=True). "
        "Use execute_code from src/learning/tools.py instead.\n"
        + "\n".join(hits)
    )


def test_no_shell_true_in_agent_loop():
    """agent_loop/tools.py must not use shell=True."""
    target = REPO / "src" / "agent_loop" / "tools.py"
    if not target.exists():
        pytest.skip("agent_loop/tools.py not present")
    content = target.read_text()
    assert "shell=True" not in content, (
        "shell=True in agent_loop/tools.py — command injection risk"
    )
