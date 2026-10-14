"""OpenAI Embeddings Provider."""
from __future__ import annotations
import os
from typing import Sequence

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class OpenAIEmbeddings:
    """مزود embeddings عبر OpenAI."""

    def __init__(self, api_key: str = None, model: str = "text-embedding-3-small"):
        if not HAS_OPENAI:
            raise ImportError("openai غير مثبت")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
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
