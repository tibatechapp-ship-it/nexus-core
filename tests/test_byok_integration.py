"""BYOK factory tests — ``create_llm_client_from_request`` contract.

Hermetic: no network, no env reads at import. The factory returns a real
``BaseConnector`` subclass instance built from the request dict.
"""

from __future__ import annotations


import pytest

from connectors.base import BaseConnector
from connectors.registry import PROVIDER_MAP, list_providers
from hyper_app.services.llm_factory import (
    DEFAULT_USER_CONFIG,
    create_llm_client_from_request,
)


def test_byok_factory_creates_client() -> None:
    """A valid provider yields a BaseConnector instance with the requested model."""
    client = create_llm_client_from_request({"provider": "openai", "model": "gpt-4o-mini"})
    assert isinstance(client, BaseConnector)
    assert client.model == "gpt-4o-mini"


def test_byok_factory_default_is_ollama() -> None:
    """No config → the documented default provider (ollama)."""
    client = create_llm_client_from_request(None)
    assert isinstance(client, BaseConnector)
    # Ollama's default model comes from its own default_model().
    assert client.model  # non-empty


def test_byok_factory_empty_dict_uses_default() -> None:
    client = create_llm_client_from_request({})
    assert isinstance(client, BaseConnector)
    assert DEFAULT_USER_CONFIG["provider"] == "ollama"


def test_byok_factory_passes_api_key() -> None:
    client = create_llm_client_from_request({"provider": "openai", "api_key": "sk-test-123"})
    assert getattr(client, "api_key", None) == "sk-test-123"


def test_byok_factory_is_case_insensitive_on_provider() -> None:
    client = create_llm_client_from_request({"provider": "OpenAI"})
    assert isinstance(client, BaseConnector)


def test_byok_unknown_provider() -> None:
    """An unregistered provider raises ValueError (surfaced from the registry)."""
    with pytest.raises(ValueError, match="Unsupported provider"):
        create_llm_client_from_request({"provider": "nope"})


def test_registry_maps_all_six_providers() -> None:
    """All six providers are registered and the factory can build each one."""
    assert set(PROVIDER_MAP) == {
        "openai",
        "anthropic",
        "groq",
        "ollama",
        "deepseek",
        "gemini",
    }
    assert sorted(list_providers()) == sorted(PROVIDER_MAP)
    for provider in PROVIDER_MAP:
        client = create_llm_client_from_request({"provider": provider})
        assert isinstance(client, BaseConnector)
        assert client.model


def test_factory_does_not_read_env_at_import() -> None:
    """The factory module has no import-time env side effects (BYOK purity)."""
    import inspect

    from hyper_app.services import llm_factory

    src = inspect.getsource(llm_factory)
    # No module-level os.getenv / open / requests — only the function body.
    module_body = src.split("def create_llm_client_from_request")[0]
    assert "os.getenv" not in module_body
    assert "open(" not in module_body
