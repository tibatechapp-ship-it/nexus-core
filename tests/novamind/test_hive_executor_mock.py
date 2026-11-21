"""Tests for hive.factory.executor — proper mocking."""
import asyncio
from unittest.mock import patch


def test_execute_agent_rejects_mock_as_real_provider():
    """A mocked LLM response must never be accepted as a real agent run."""
    from novamind.core.hive.factory import executor

    async def fake_llm(prompt):
        return {
            "ok": True,
            "simulated": True,
            "text": "Mocked Success",
            "provider": "mock",
            "model": "test-model",
            "tokens": 100,
        }

    # Patch the symbol INSIDE executor's namespace, not llm_wrapper
    with patch.object(executor, "make_llm_call", return_value=fake_llm), \
         patch.object(executor, "is_llm_available", True):
        result = asyncio.run(
            executor.execute_agent("coder", "Hello World")
        )

    assert result.get("success") is False
    assert result.get("status") == "simulated_provider_rejected", \
        f"Mock output was not rejected: {result}"


def test_execute_agent_handles_llm_exception():
    """Test error handling when LLM fails."""
    from novamind.core.hive.factory import executor

    async def failing_llm(prompt):
        raise RuntimeError("provider down")

    with patch.object(executor, "make_llm_call", return_value=failing_llm), \
         patch.object(executor, "is_llm_available", True):
        result = asyncio.run(
            executor.execute_agent("coder", "Trigger Error")
        )

    # Error captured
    assert result.get("success") is False or result.get("status") == "error", \
        f"Expected error, got: {result}"

    err_str = str(result.get("error", "")) + str(result.get("message", ""))
    assert "RuntimeError" in err_str or "provider down" in err_str or "LLM failed" in err_str, \
        f"Expected error info, got: {result}"
