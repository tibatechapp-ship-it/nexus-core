"""Agent-RAG Bridge — يجعل كل وكيل يستخدم RAG تلقائياً."""
from __future__ import annotations
import os
from typing import Optional
from src.memory.rag_engine import RAGEngine


class AgentRAGBridge:
    """جسر RAG للوكلاء — يثري prompts بالسياق."""

    _instance: Optional["AgentRAGBridge"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.rag = RAGEngine(
            vector_store_path=os.path.expanduser("~/.nexus/data/rag.db")
        )
        self._initialized = True

    def enrich_prompt(self, prompt: str, k: int = 3) -> str:
        """يُثري الـ prompt بسياق من الذاكرة."""
        try:
            docs = self.rag.retrieve(prompt, k=k)
        except Exception:
            return prompt
        if not docs:
            return prompt
        context = "\n".join(f"  • {d.text}" for d in docs)
        return f"""{prompt}

━━━ سياق من الذاكرة ━━━
{context}
━━━━━━━━━━━━━━━━━━━━━━"""

    def remember(self, text: str, doc_id: str = None) -> str:
        """يحفظ معلومة."""
        doc_id = doc_id or f"mem_{abs(hash(text)) & 0xFFFFFF:x}"
        self.rag.add_document(doc_id, text)
        return doc_id

    def recall(self, query: str, k: int = 3) -> list:
        """يسترجع معلومات ذات صلة."""
        return self.rag.retrieve(query, k=k)


_bridge = None

def get_bridge() -> AgentRAGBridge:
    global _bridge
    if _bridge is None:
        _bridge = AgentRAGBridge()
    return _bridge
