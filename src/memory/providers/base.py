"""Embedding providers — base interface + registry."""
from __future__ import annotations
import os
from typing import Optional, Protocol, Sequence

__all__ = ["EmbeddingProvider", "get_provider", "resolve_api_key"]


class EmbeddingProvider(Protocol):
    """واجهة مزود embeddings."""

    def embed(self, text: str) -> Sequence[float]:
        """يحوّل نصاً إلى vector."""
        ...


def resolve_api_key(prefix: str, env: Optional[dict] = None,
                    max_suffix: int = 20) -> str:
    """أول مفتاح متاح: ``PREFIX`` ثم ``PREFIX_1`` .. ``PREFIX_N``.

    المشاريع تضع المفاتيح إمّا بلا لاحقة أو مرقَّمة (``GEMINI_API_KEY_1`` …)؛
    هذه الدالة توحّد الحالتين حتى لا يفشل المزوّد بسبب فرق تسمية.
    """
    env = os.environ if env is None else env
    direct = env.get(prefix)
    if direct:
        return direct
    for i in range(1, max_suffix + 1):
        value = env.get(f"{prefix}_{i}")
        if value:
            return value
    return ""


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
