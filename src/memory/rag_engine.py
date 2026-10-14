"""RAG Engine — دمج البحث الدلالي مع LLM."""
from __future__ import annotations
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.memory.embeddings import HashingEmbedder
from src.memory.vector_store import SQLiteVecStore


class RAGEngine:
    """محرك RAG: يجمع السياق من vector store ويمرره للـ LLM."""

    def __init__(self, vector_store_path: str = None,
                 embedder=None, llm_router=None):
        self.vector_store_path = vector_store_path or os.path.join(
            os.path.expanduser("~"), ".nexus", "data", "vectors.db"
        )
        os.makedirs(os.path.dirname(self.vector_store_path), exist_ok=True)

        self.embedder = embedder or HashingEmbedder(dim=512)
        self.store = SQLiteVecStore(self.vector_store_path, dim=512)
        self.llm = llm_router

    def add_document(self, doc_id: str, text: str, metadata: dict = None) -> None:
        """يضيف وثيقة."""
        emb = self.embedder(text)
        self.store.add(doc_id, text, emb, metadata)

    def add_documents(self, docs: list) -> int:
        """يضيف عدة وثائق: [(id, text), ...]."""
        count = 0
        for item in docs:
            if isinstance(item, tuple) and len(item) >= 2:
                self.add_document(item[0], item[1])
                count += 1
        return count

    def retrieve(self, query: str, k: int = 5) -> list:
        """يستعيد أقرب الوثائق."""
        query_emb = self.embedder(query)
        return self.store.search(query_emb, k=k)

    def generate(self, query: str, k: int = 5, **llm_kwargs) -> dict:
        """يولّد إجابة مع سياق من RAG."""
        # 1. استرجاع
        docs = self.retrieve(query, k=k)

        if not docs:
            context = ""
        else:
            context = "\n\n".join(
                f"[{d.id}] {d.text}" for d in docs
            )

        # 2. بناء الـ prompt
        if context:
            system = (
                f"أنت مساعد ذكي. استخدم السياق التالي للإجابة:\n\n"
                f"=== السياق ===\n{context}\n=== نهاية السياق ===\n\n"
                f"أجب بدقة بناءً على السياق. إذا لم تجد الإجابة، قل ذلك."
            )
        else:
            system = "أنت مساعد ذكي. أجب على السؤال."

        # 3. استدعاء LLM
        if self.llm:
            return self.llm.generate_for_task(
                task_type="analysis",
                prompt=query,
                system=system,
                **llm_kwargs,
            )
        return {
            "ok": True,
            "text": f"[RAG Context]\n{context}\n\n[Query]\n{query}",
            "provider": "local-rag",
            "elapsed": 0.0,
        }

    def close(self):
        self.store.close()
