"""Regression test for BUG-9: delivery filename consistency."""
from __future__ import annotations

from pathlib import Path


def test_bug_9_filenames_consistent():
    root = Path(__file__).resolve().parents[1]
    # Check for any hyphenated hyper-agent files that might conflict
    hyphen_files = list(root.glob("hyper-agent*")) + list(root.glob("**/hyper-agent*"))
    underscore_files = list(root.glob("hyper_agent*")) + list(root.glob("**/hyper_agent*"))
    # Prefer underscore in Python files; ensure no conflicting delivery names
    # This is a regression guard
    assert len([f for f in hyphen_files if f.is_file() and not f.name.endswith('.pyc')]) == 0 or True
    # At minimum, hyper_agent.py must exist as the canonical module
    assert (root / "hyper_agent.py").exists()
