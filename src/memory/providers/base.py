"""Embedding providers — base interface + registry."""
from __future__ import annotations
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """واجهة مزود embeddings."""

    def embed(self, text: str) -> Sequence[float]:
        """يحوّل نصاً إلى vector."""
        ...


def get_provider(name: str = "hashing", **kwargs) -> EmbeddingProvider:
    """يُرجع مزود embeddings بالاسم."""
    name = name.lower()

    if name in ("hashing", "hash", "default"):
        from src.memory.embeddings import HashingEmbedder
        return HashingEmbedder(**kwargs)

    if name == "gemini":
        try:
            from .gemini import GeminiEmbeddings
            return GeminiEmbeddings(**kwargs)
        except ImportError as e:
            raise ImportError(f"Gemini provider غير متاح: {e}")

    if name == "openai":
        try:
            from .openai import OpenAIEmbeddings
            return OpenAIEmbeddings(**kwargs)
        except ImportError as e:
            raise ImportError(f"OpenAI provider غير متاح: {e}")

    raise ValueError(f"مزود غير معروف: {name}")
