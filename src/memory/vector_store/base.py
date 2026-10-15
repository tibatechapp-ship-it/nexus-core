"""Abstract VectorStore interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


@dataclass
class SearchResult:
    """نتيجة بحث دلالي."""
    id: str
    text: str
    distance: float
    metadata: dict | None = None


class VectorStore(ABC):
    """واجهة موحدة لمخازن vectors."""

    @abstractmethod
    def add(self, id: str, text: str, embedding: Sequence[float], metadata: dict | None = None) -> None:
        """يضيف vector."""
        ...

    @abstractmethod
    def search(self, embedding: Sequence[float], k: int = 5) -> list[SearchResult]:
        """يبحث عن أقرب vectors."""
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        """يحذف vector."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """يحذف كل شيء."""
        ...
