"""OpenAI Embeddings Provider."""
from __future__ import annotations
from typing import Sequence

from .base import resolve_api_key

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class OpenAIEmbeddings:
    """مزود embeddings عبر OpenAI."""

    # بُعد text-embedding-3-small
    dim = 1536

    def __init__(self, api_key: str = None, model: str = "text-embedding-3-small"):
        if not HAS_OPENAI:
            raise ImportError("openai غير مثبت")
        self.api_key = api_key or resolve_api_key("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY مطلوب")
        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def embed(self, text: str) -> Sequence[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding
