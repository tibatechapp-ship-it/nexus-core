"""Agent-RAG Bridge — يجعل كل وكيل يستخدم RAG تلقائياً."""
from __future__ import annotations
from typing import Optional, Any
from src.memory.rag_engine import RAGEngine


class AgentRAGBridge:
    """جسر RAG للوكلاء — يثري prompts بالسياق."""

    _instance: Optional["AgentRAGBridge"] = None

    def __new__(cls: Any) -> Any:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # type: ignore[has-type]
        return cls._instance

    def __init__(self: Any) -> None:
        if self._initialized:  # type: ignore[has-type]
            return
        # ═══ اختيار المزوّد من NEXUS_EMBEDDINGS (افتراضي: hashing → rag.db) ═══
        from src.memory.embedding_config import resolve_rag
        resolved = resolve_rag()
        self.embedding_spec = resolved.spec
        self.embedding_fallback = resolved.fallback_reason
        if resolved.fallback_reason:
            print("[RAG] " + resolved.fallback_reason)
        self.rag = RAGEngine(
            vector_store_path=resolved.path,
            embedder=resolved.embedder,
            dim=resolved.dim,
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

    def remember(self, text: str, doc_id: str | None = None) -> str:
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
