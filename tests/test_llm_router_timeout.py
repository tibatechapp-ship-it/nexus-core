"""v1.32.1 — the OpenAI client must carry an explicit, sane request budget.

The SDK default (httpx) is a 600s client timeout: a hung provider would block
a caller for 10 minutes. These tests assert on the CLIENT OBJECT (or the
kwargs handed to OpenAI), never on source text — a grep for "timeout=" would
pass on a comment.
"""
import importlib

import pytest

openai = pytest.importorskip("openai")

from novamind.core import llm_router
from novamind.core.llm_router import (
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    ProviderConfig,
)


def _openai_provider() -> ProviderConfig:
    return ProviderConfig(
        name="openai_unit",
        api_key="sk-unit-test",
        base_url="https://example.invalid/v1",
        models={"fast": "gpt-x", "smart": "gpt-x"},
    )


def _fresh_router():
    router = llm_router.LLMRouter.__new__(llm_router.LLMRouter)
    router._clients = {}
    return router


def test_openai_client_has_explicit_timeout():
    """A real client is built and its timeout is below the 600s SDK default."""
    client = _fresh_router()._get_client(_openai_provider())
    timeout = getattr(client, "timeout", None)
    assert timeout is not None, "OpenAI client has no timeout attribute"
    assert timeout < 600.0, f"timeout {timeout} is not below the 600s default"
    assert getattr(client, "max_retries", None) == DEFAULT_RETRIES


def test_timeout_default_in_range():
    """The module default must be a bounded, non-hanging value."""
    assert 30.0 <= DEFAULT_TIMEOUT <= 120.0
    assert DEFAULT_RETRIES >= 0


def test_openai_call_passes_the_budget(monkeypatch):
    """The constructor receives timeout/max_retries kwargs explicitly."""
    captured = {}

    class _Spy:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", _Spy)
    _fresh_router()._get_client(_openai_provider())
    assert captured["timeout"] == DEFAULT_TIMEOUT
    assert captured["max_retries"] == DEFAULT_RETRIES


def test_timeout_env_override(monkeypatch):
    """NEXUS_LLM_TIMEOUT / NEXUS_LLM_RETRIES re-read at import time win."""
    monkeypatch.setenv("NEXUS_LLM_TIMEOUT", "180")
    monkeypatch.setenv("NEXUS_LLM_RETRIES", "1")
    reloaded = importlib.reload(llm_router)
    try:
        assert reloaded.DEFAULT_TIMEOUT == 180.0
        assert reloaded.DEFAULT_RETRIES == 1
    finally:
        monkeypatch.delenv("NEXUS_LLM_TIMEOUT", raising=False)
        monkeypatch.delenv("NEXUS_LLM_RETRIES", raising=False)
        importlib.reload(llm_router)
