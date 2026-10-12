"""Semantic memory."""
import logging
from typing import List, Dict, Any, Optional
from .embeddings import embed
from .vector_store import get_store

logger = logging.getLogger("SemanticMemory")

class SemanticMemory:
    DEFAULT_NS = "general"
    async def remember(self, text, namespace=None, meta=None):
        ns = namespace or self.DEFAULT_NS
        emb = await embed(text)
        if not emb: return -1
        return get_store().add(ns, text, emb, meta)
    async def recall(self, query, namespace=None, top_k=5):
        ns = namespace or self.DEFAULT_NS
        emb = await embed(query)
        if not emb: return []
        return get_store().search(ns, emb, top_k=top_k)
    def stats(self):
        s = get_store()
        return {"total": s.count(), "namespaces": s.namespaces()}

_memory = None
def get_memory():
    global _memory
    if _memory is None: _memory = SemanticMemory()
    return _memory
