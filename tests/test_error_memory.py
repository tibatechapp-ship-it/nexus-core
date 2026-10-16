"""Tests for error_memory — offline/hermetic."""
from __future__ import annotations

import pytest

from novamind.error_memory import ErrorMemory, get_error_memory


@pytest.fixture
def temp_memory(tmp_path):
    """Fresh ErrorMemory in temp dir."""
    return ErrorMemory(path=tmp_path / "test.jsonl")


def test_log_writes_to_file(temp_memory):
    temp_memory.log("ValueError", "ctx", "msg")
    assert temp_memory.path.exists()
    content = temp_memory.path.read_text(encoding="utf-8")
    assert "ValueError" in content
    assert "ctx" in content


def test_stats_counts_by_type(temp_memory):
    temp_memory.log("E1", "c", "m")
    temp_memory.log("E1", "c", "m")
    temp_memory.log("E2", "c", "m")
    assert temp_memory.stats() == {"E1": 2, "E2": 1}


def test_recent_returns_last_n(temp_memory):
    for i in range(10):
        temp_memory.log("E", "c", f"m{i}")
    recent = temp_memory.recent(3)
    assert len(recent) == 3
    assert recent[-1]["error_message"] == "m9"


def test_error_message_truncated(temp_memory):
    long_msg = "x" * 1000
    temp_memory.log("E", "c", long_msg)
    assert len(temp_memory.recent(1)[0]["error_message"]) <= 500


def test_extra_kwargs_stored(temp_memory):
    temp_memory.log("E", "c", "m", provider="groq", model="llama")
    entry = temp_memory.recent(1)[0]
    assert entry["provider"] == "groq"
    assert entry["model"] == "llama"


def test_singleton_returns_same_instance():
    a = get_error_memory()
    b = get_error_memory()
    assert a is b
