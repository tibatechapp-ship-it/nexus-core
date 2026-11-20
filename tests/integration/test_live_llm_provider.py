"""Credentialed smoke test for a real configured LLM provider.

Run explicitly with NEXUS_RUN_LIVE_PROVIDER_TESTS=1 and provider credentials
available in the environment or supported .env files. This test is skipped in
ordinary hermetic CI and never substitutes a mock provider.
"""
import os

import pytest

from novamind.core.llm_router import refresh_router


@pytest.mark.skipif(
    os.getenv("NEXUS_RUN_LIVE_PROVIDER_TESTS") != "1",
    reason="explicit opt-in required for live provider network test",
)
def test_live_provider_returns_non_simulated_response():
    router = refresh_router()
    assert router.providers, "No real provider credentials are configured"

    marker = "NEXUS_LIVE_PROVIDER_OK"
    result = router.generate(
        f"Reply with exactly this marker and no other text: {marker}",
        system="You are running a provider connectivity smoke test.",
        role="fast",
        temperature=0,
        max_tokens=48,
        allow_fallback=True,
    )

    assert result["ok"] is True, result.get("error")
    assert result.get("simulated") is False
    assert result["provider"] != "mock"
    assert marker in result["text"]
