"""Tests for hive.factory.llm_wrapper."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from novamind.core.hive.factory import llm_wrapper


class FakeRouter:
    """A simple fake router that echoes back parameters to verify passing."""
    async def generate(self, prompt, model="default", **kwargs):
        # Simulate a real API response structure
        return {
            "text": f"Response to: {prompt[:20]}",
            "model": model,       # Echo back the model used
            "provider": "fake-01", # Hardcoded provider for test consistency
            "usage": {"tokens": len(prompt.split())}
        }


@pytest.mark.asyncio
async def test_make_llm_call_with_fake_router():
    """Verify that make_llm_call correctly passes model and extracts provider."""
    router = FakeRouter()
    
    # Create the callable with specific model
    call_fn = llm_wrapper.make_llm_call(router=router, model="gpt-4-test")
    
    # Execute
    result = await call_fn("Hello World")
    
    # Assertions
    assert result["text"] != "", "Text should not be empty"
    # Key Fix: Ensure the model passed to make_llm_call is reflected in result
    assert result["model"] == "gpt-4-test", f"Expected model 'gpt-4-test', got '{result['model']}'"
    # Verify provider extraction works
    assert result["provider"] == "fake-01", f"Expected provider 'fake-01', got '{result['provider']}'"


@pytest.mark.asyncio
async def test_make_llm_call_without_router_returns_mock():
    """Verify fallback behavior when NO router is provided (strict local mock)."""
    # Explicitly pass router=None to force local mock logic inside llm_wrapper
    call_fn = llm_wrapper.make_llm_call(router=None, model="local-mock-model")
    
    result = await call_fn("Hi there")
    
    # The local mock in llm_wrapper.py now guarantees [MOCK] prefix
    assert "[MOCK]" in result["text"], f"Text did not contain [MOCK]: {result['text']}"
    # Provider should be our internal mock identifier
    assert result["provider"] == "mock-provider", f"Expected 'mock-provider', got '{result['provider']}'"
    # Model should match what was requested
    assert result["model"] == "local-mock-model"
