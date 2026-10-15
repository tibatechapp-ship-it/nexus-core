"""Gemini Embeddings Provider."""
from __future__ import annotations
from typing import Sequence, Any

from .base import resolve_api_key

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class GeminiEmbeddings:
    """مزود embeddings عبر Gemini API (متوافق OpenAI)."""

    # بُعد text-embedding-004
    dim = 768

    def __init__(self: Any, api_key: str | None = None, model: str = "text-embedding-004") -> None:
        if not HAS_OPENAI:
            raise ImportError("openai غير مثبت")
        self.api_key = api_key or resolve_api_key("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY مطلوب")
        # Gemini متوافق مع OpenAI API
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.model = model

    def embed(self, text: str) -> Sequence[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding
