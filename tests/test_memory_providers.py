"""Tests for the embedding-provider registry (offline paths only).

The Gemini / OpenAI providers need the optional ``openai`` package and a network
key, so they are not exercised here — only the stdlib hashing provider and the
registry's error handling.
"""

from __future__ import annotations

import pytest

from src.memory.embeddings import HashingEmbedder
from src.memory.providers.base import get_provider


@pytest.mark.parametrize("name", ["hashing", "HASHING", "hash", "default"])
def test_get_provider_returns_hashing(name):
    provider = get_provider(name)
    assert isinstance(provider, HashingEmbedder)


def test_get_provider_unknown_name_raises():
    with pytest.raises(ValueError):
        get_provider("does-not-exist")


def test_hashing_provider_satisfies_embed_protocol():
    """HashingEmbedder must expose ``.embed`` (EmbeddingProvider protocol)."""
    provider = get_provider("hashing")
    vector = provider.embed("hello world")
    assert isinstance(vector, list)
    # .embed and __call__ agree
    assert vector == HashingEmbedder()("hello world")


def test_get_provider_gemini_without_key_raises(monkeypatch):
    """Gemini provider needs a key (or the openai package) — must fail loudly."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises((ImportError, ValueError)):
        get_provider("gemini")
