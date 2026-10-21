"""Regression test for BUG-9: delivery filename consistency."""

from pathlib import Path


def test_no_hyphenated_hyper_agent_shadow() -> None:
    """No ``hyper-agent*.py`` may shadow the canonical ``hyper_agent.py``."""
    root = Path(__file__).resolve().parents[1]
    shadow = [
        p
        for p in root.glob("hyper-agent*.py")
        if p.is_file()
    ]
    assert not shadow, f"hyphenated shadow files present: {shadow}"


def test_canonical_hyper_agent_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "hyper_agent.py").is_file()
