"""Tests for the embedding-provider registry + RAG embedding configuration.

The Gemini / OpenAI providers need the optional ``openai`` package and a network
key, so they are not exercised with live calls here — only the stdlib hashing
provider, the registry's error handling, and the ``NEXUS_EMBEDDINGS`` resolver.
"""

from __future__ import annotations

import pytest

from src.memory.embeddings import HashingEmbedder
from src.memory.providers.base import get_provider, resolve_api_key
from src.memory import embedding_config as ec


# ───────────────────────────── providers ─────────────────────────────

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
    """Gemini needs a key — with no key of any spelling it must fail loudly."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    with pytest.raises((ImportError, ValueError)):
        get_provider("gemini")


def test_get_provider_gemini_accepts_prefixed_key(monkeypatch):
    """A prefixed key (``GEMINI_API_KEY_1``) must satisfy the provider."""
    openai = pytest.importorskip("openai")  # noqa: F841
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_1", "test-key")
    provider = get_provider("gemini")
    assert provider.dim == 768


# ─────────────────────────── resolve_api_key ──────────────────────────

def test_resolve_api_key_prefers_direct():
    assert resolve_api_key("K", env={"K": "direct", "K_1": "one"}) == "direct"


def test_resolve_api_key_falls_back_to_first_suffix():
    assert resolve_api_key("K", env={"K_2": "two", "K_5": "five"}) == "two"


def test_resolve_api_key_missing_returns_empty():
    assert resolve_api_key("K", env={}) == ""


# ──────────────────────────── resolve_spec ────────────────────────────

@pytest.mark.parametrize("raw", [None, "", "   ", "auto", "AUTO"])
def test_resolve_spec_default(raw):
    env = {} if raw is None else {ec.ENV_VAR: raw}
    assert ec.resolve_spec(env=env) == ec.DEFAULT_PROVIDER


@pytest.mark.parametrize("raw,expected", [
    ("hashing", "hashing"), ("hash", "hashing"), ("builtin", "hashing"),
    ("gemini", "gemini"), ("google", "gemini"), ("openai", "openai"),
    ("Gemini", "gemini"),
])
def test_resolve_spec_aliases(raw, expected):
    assert ec.resolve_spec(raw, env={}) == expected


def test_resolve_spec_argument_beats_env():
    assert ec.resolve_spec("openai", env={ec.ENV_VAR: "gemini"}) == "openai"


def test_resolve_spec_unknown_raises():
    with pytest.raises(ValueError):
        ec.resolve_spec("nonsense", env={})


# ───────────────────────── dim / store path ───────────────────────────

def test_dim_for_known_providers():
    assert ec.dim_for("hashing") == 512
    assert ec.dim_for("gemini") == 768
    assert ec.dim_for("openai") == 1536


def test_dim_for_unknown_defaults():
    assert ec.dim_for("whatever") == ec.DEFAULT_DIM


def test_store_filename_hashing_keeps_legacy_rag_db():
    assert ec.store_filename("hashing") == "rag.db"


def test_store_filename_other_providers_are_separate():
    assert ec.store_filename("gemini") == "rag-gemini-768.db"
    assert ec.store_filename("openai") == "rag-openai-1536.db"


def test_store_path_for_uses_base_dir():
    path = ec.store_path_for("gemini", base_dir="/data")
    assert path == "/data/rag-gemini-768.db"


# ─────────────────────────── build_embedder ───────────────────────────

def test_build_embedder_hashing():
    embedder, dim, reason = ec.build_embedder("hashing")
    assert isinstance(embedder, HashingEmbedder)
    assert dim == 512
    assert reason is None


def test_build_embedder_falls_back_on_provider_failure(monkeypatch):
    def _boom(name, **kwargs):
        raise ImportError("simulated missing dependency")

    monkeypatch.setattr("src.memory.providers.base.get_provider", _boom)
    embedder, dim, reason = ec.build_embedder("gemini")
    assert isinstance(embedder, HashingEmbedder)
    assert dim == 512
    assert reason and "gemini" in reason


# ─────────────────────────── resolve_rag ─────────────────────────────

def test_resolve_rag_default(tmp_path):
    r = ec.resolve_rag(env={}, base_dir=str(tmp_path))
    assert r.spec == "hashing"
    assert r.dim == 512
    assert r.path.endswith("rag.db")
    assert r.fallback_reason is None


def test_resolve_rag_unknown_spec_falls_back(tmp_path):
    r = ec.resolve_rag(env={ec.ENV_VAR: "bogus"}, base_dir=str(tmp_path))
    assert r.spec == "hashing"
    assert r.dim == 512
    assert r.path.endswith("rag.db")
    assert r.fallback_reason


def test_resolve_rag_provider_failure_keeps_hashing_path(monkeypatch, tmp_path):
    def _boom(name, **kwargs):
        raise ImportError("nope")

    monkeypatch.setattr("src.memory.providers.base.get_provider", _boom)
    r = ec.resolve_rag(env={ec.ENV_VAR: "gemini"}, base_dir=str(tmp_path))
    # رجع فعلياً إلى hashing → المسار والقاعدة يجب أن يكونا الافتراضي، لا rag-gemini-*
    assert r.spec == "hashing"
    assert r.dim == 512
    assert r.path.endswith("rag.db")
    assert r.fallback_reason


# ──────────────────────── RAGEngine dim round-trip ────────────────────

def test_rag_engine_honors_dim(tmp_path):
    pytest.importorskip("sqlite3")
    from src.memory.rag_engine import RAGEngine

    embedder = HashingEmbedder(dim=64)
    engine = RAGEngine(
        vector_store_path=str(tmp_path / "small.db"),
        embedder=embedder,
        dim=64,
    )
    try:
        assert engine.dim == 64
        engine.add_document("d1", "استخدام قاعدة بيانات sqlite للذاكرة")
        engine.add_document("d2", "weather is nice today")
        hits = engine.retrieve("sqlite memory", k=2)
        assert hits, "expected at least one hit"
        assert hits[0].id == "d1"
    finally:
        engine.close()


def test_rag_engine_dim_from_embedder_attribute(tmp_path):
    from src.memory.rag_engine import RAGEngine

    engine = RAGEngine(
        vector_store_path=str(tmp_path / "auto.db"),
        embedder=HashingEmbedder(dim=32),
    )
    try:
        assert engine.dim == 32  # derived from embedder.dim
    finally:
        engine.close()
