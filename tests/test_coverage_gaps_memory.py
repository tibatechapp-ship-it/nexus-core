"""Coverage-gap tests — the memory layer (protocol/ABC stub bodies, provider
fallbacks, and the defensive branches in the store helpers).

Everything in this module covers a line/branch that no other test reached:
the declared-but-never-called protocol stubs, the optional-``openai`` import
fallbacks, and the "no parent directory" / "row without an embedding" paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.memory.base import connect
from src.memory.embedding_config import build_embedder, dim_for
from src.memory.embeddings import Embedder, HashingEmbedder
from src.memory.emotional import Tone, _resolve_tone
from src.memory.procedural import ProceduralMemory, Skill
from src.memory.providers.base import EmbeddingProvider, get_provider
from src.memory.rag_engine import RAGEngine
from src.memory.vector_store.base import VectorStore

_MISSING: object = object()


# --------------------------------------------------------------------------- #
# declared protocol / ABC stub bodies
#
# ``Protocol`` and ``ABC`` stub methods are unreachable through ordinary use
# (the ABC refuses instantiation, the protocol is never instantiated at all),
# yet the bodies are real statements. Calling the unbound functions documents
# that the stubs exist and never raise.
# --------------------------------------------------------------------------- #
def test_embedder_protocol_stub_body_is_callable() -> None:
    assert Embedder.__call__(object(), "text") is None


def test_embedding_provider_stub_body_is_callable() -> None:
    assert EmbeddingProvider.embed(object(), "text") is None


def test_vector_store_abstract_stub_bodies_are_callable() -> None:
    store = object()
    assert VectorStore.add(store, "id", "text", [0.1]) is None
    assert VectorStore.search(store, [0.1]) is None
    assert VectorStore.delete(store, "id") is None
    assert VectorStore.clear(store) is None


# --------------------------------------------------------------------------- #
# embedding providers
# --------------------------------------------------------------------------- #
def test_build_embedder_returns_a_live_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-default provider that *does* construct returns (provider, dim, None).

    ``build_embedder`` reads the credential from the environment (it forwards no
    ``**kwargs`` to a non-default provider), so the key is set here.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider, dim, reason = build_embedder("openai")
    assert type(provider).__name__ == "OpenAIEmbeddings"
    assert dim == dim_for("openai") == 1536
    assert reason is None


def test_get_provider_constructs_openai_client() -> None:
    provider = get_provider("openai", api_key="test-key")
    assert provider.dim == 1536


def _exec_module_without(module_name: str, hide: str) -> dict[str, object]:
    """Execute a module's source with ``hide`` importable-as-missing.

    The module object itself is left untouched (nothing is reloaded into
    ``sys.modules``), so no other test can observe the degraded variant.
    """
    module = __import__(module_name, fromlist=["__name__"])
    source = Path(str(module.__file__)).read_text(encoding="utf-8")
    namespace: dict[str, object] = {
        "__name__": f"{module_name}_variant",
        "__package__": module.__package__,
    }
    saved = sys.modules.get(hide, _MISSING)
    sys.modules[hide] = None  # type: ignore[assignment]
    try:
        exec(compile(source, str(module.__file__), "exec"), namespace)
    finally:
        if saved is _MISSING:
            sys.modules.pop(hide, None)
        else:
            sys.modules[hide] = saved  # type: ignore[assignment]
    return namespace


@pytest.mark.parametrize(
    "module_name",
    ["src.memory.providers.gemini", "src.memory.providers.openai"],
)
def test_embedding_providers_degrade_without_openai(module_name: str) -> None:
    namespace = _exec_module_without(module_name, "openai")
    assert namespace["HAS_OPENAI"] is False
    embeddings_class = namespace["GeminiEmbeddings" if "gemini" in module_name else "OpenAIEmbeddings"]
    with pytest.raises(ImportError):
        embeddings_class(api_key="test-key")  # type: ignore[operator]


def test_embedding_providers_have_openai_installed() -> None:
    """Guard: the fallback test above is only meaningful when openai *is* here."""
    import src.memory.providers.gemini as gemini
    import src.memory.providers.openai as openai_provider

    assert gemini.HAS_OPENAI is True
    assert openai_provider.HAS_OPENAI is True


# --------------------------------------------------------------------------- #
# emotional tone resolution
# --------------------------------------------------------------------------- #
def test_resolve_tone_classifies_a_free_text_string() -> None:
    """A string that is not a known label falls through to the classifier."""
    resolved = _resolve_tone("أنا سعيد جداً بهذا العمل الرائع", None)
    assert isinstance(resolved, Tone)


# --------------------------------------------------------------------------- #
# procedural / skill views
# --------------------------------------------------------------------------- #
def test_skill_to_dict_is_json_serialisable() -> None:
    skill = Skill(
        name="deploy",
        description="ship it",
        steps=("build",),
        examples=("make deploy",),
        tags=("web",),
        uses=4,
        successes=3,
    )
    payload = skill.to_dict()
    assert payload["name"] == "deploy"
    assert payload["steps"] == ["build"]
    assert payload["success_rate"] == pytest.approx(0.75)


def test_vector_find_falls_back_to_lexical_for_rows_without_embedding() -> None:
    """A row whose embedding column is empty is scored lexically instead."""
    conn = connect(":memory:")
    try:
        store = ProceduralMemory(conn, embedder=HashingEmbedder(dim=8))
        store.learn("alpha", "prepare the alpha report", steps=["a"], tags=["alpha"])
        store._execute("UPDATE skills SET embedding = NULL")
        # No lexical overlap at all → the row scores 0.0 and is dropped.
        assert store.find("zzzz_unknown_token_zzzz") == []
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# stores on a relative path (no parent directory to create)
# --------------------------------------------------------------------------- #
def test_rag_engine_relative_store_path_skips_parent_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    engine = RAGEngine(vector_store_path="vectors.db", dim=4)
    try:
        assert engine.store.path == "vectors.db"
        assert (tmp_path / "vectors.db").exists()
    finally:
        engine.store.close()
