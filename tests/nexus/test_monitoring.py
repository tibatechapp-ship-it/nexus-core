"""Tests for monitoring."""
import os
import sys
import time
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from src.nexus.monitoring import Monitor


@pytest.fixture
def mon(tmp_path):
    return Monitor(log_dir=str(tmp_path / "metrics"))


def test_empty_stats(mon):
    stats = mon.get_today_stats()
    assert stats["total_calls"] == 0
    assert stats["success_rate"] == 0.0


def test_log_successful_call(mon):
    mon.log_call(
        provider="groq_01",
        model="qwen",
        elapsed=1.5,
        ok=True,
        prompt="test prompt",
        response="test response",
    )
    stats = mon.get_session_stats()
    assert stats["total_calls"] == 1
    assert stats["successes"] == 1
    assert stats["failures"] == 0
    assert stats["success_rate"] == 100.0


def test_log_failed_call(mon):
    mon.log_call(
        provider="groq_01",
        model="qwen",
        elapsed=0.5,
        ok=False,
        error="test error",
    )
    stats = mon.get_session_stats()
    assert stats["failures"] == 1
    assert stats["success_rate"] == 0.0


def test_token_estimation(mon):
    mon.log_call(
        provider="groq",
        model="qwen",
        elapsed=1.0,
        ok=True,
        prompt="a" * 100,  # ~25 tokens
        response="b" * 40,  # ~10 tokens
    )
    stats = mon.get_session_stats()
    assert stats["total_tokens_in"] >= 20
    assert stats["total_tokens_out"] >= 8


def test_cost_calculation(mon):
    mon.log_call(
        provider="groq",
        model="qwen",
        elapsed=1.0,
        ok=True,
        prompt="x" * 4000,  # ~1000 tokens
        response="y" * 4000,  # ~1000 tokens
    )
    stats = mon.get_session_stats()
    # 1000 in @ $0.05/1M + 1000 out @ $0.08/1M = ~$0.00013
    assert stats["total_cost_usd"] > 0
    assert stats["total_cost_usd"] < 0.001


def test_by_provider_stats(mon):
    mon.log_call(provider="groq_01", model="qwen", elapsed=1.0, ok=True, prompt="a", response="b")
    mon.log_call(provider="groq_02", model="qwen", elapsed=1.0, ok=True, prompt="a", response="b")
    mon.log_call(provider="gemini_1", model="gemini", elapsed=1.0, ok=True, prompt="a", response="b")

    stats = mon.get_session_stats()
    assert len(stats["by_provider"]) == 3
    assert stats["by_provider"]["groq_01"]["calls"] == 1


def test_clear(mon):
    mon.log_call(provider="groq", model="qwen", elapsed=1.0, ok=True, prompt="a", response="b")
    count = mon.clear_today()
    assert count == 1
    assert mon.get_today_stats()["total_calls"] == 0
