"""
RAG Agent v2 — Enhanced semantic search with real code content.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("core.rag.rag_agent")

from novamind.core.paths import NOVAMIND_HOME as BASE


class RAGAgent:
    """Retrieval-Augmented Generation for codebases."""

    def __init__(self):
        self._store = None
        self._kg = None

    def _get_store(self):
        if self._store is None:
            from novamind.core.rag.vector_store import code_store
            self._store = code_store
        return self._store

    def _get_kg(self):
        if self._kg is None:
            from novamind.core.rag.knowledge_graph import code_graph
            self._kg = code_graph
        return self._kg

    def index_codebase(self, directory: Optional[str] = None) -> Dict:
        """Index a directory into both VS and KG with real code."""
        from novamind.core.rag.code_indexer import code_indexer
        from novamind.core.rag.knowledge_graph import KnowledgeGraph
        from novamind.core.rag.vector_store import VectorStore

        directory = Path(directory) if directory else BASE / "agents"

        # Fresh KG
        kg = KnowledgeGraph("code")
        kg.clear()

        # Index
        result = code_indexer.index_dir(directory, kg)
        documents = result.get("documents", [])

        # Fresh VS with all documents
        store = VectorStore("code")
        store.clear()

        if documents:
            store.add_many(documents)

        # Update singletons
        self._kg = kg
        self._store = store

        return {
            "ok": True,
            "directory": str(directory),
            "kg_stats": kg.stats(),
            "vs_stats": store.stats(),
            "indexer_stats": result.get("stats", {}),
            "documents_count": len(documents),
        }

    def query(self, question: str, limit: int = 5,
              use_llm: bool = False) -> Dict:
        """Query the codebase."""
        store = self._get_store()
        kg = self._get_kg()

        # Search
        results = store.search(question, limit=limit)

        # Enrich
        enriched = []
        for r in results:
            node_id = r.get("metadata", {}).get("node_id")
            node = kg.nodes.get(node_id, {}) if node_id else {}

            enriched.append({
                "text": r["text"][:300],
                "score": r["score"],
                "node_id": node_id,
                "metadata": r.get("metadata", {}),
                "node": node,
            })

        # Context
        context_lines = []
        for e in enriched:
            meta = e.get("metadata", {})
            ntype = meta.get("type", "?")
            name = meta.get("name", meta.get("node_id", "?"))
            context_lines.append(f"• [{ntype}] {name} (score: {e['score']:.2f})")

        context = "\n".join(context_lines) if context_lines else "(no results)"

        # LLM
        answer = None
        if use_llm and enriched:
            answer = self._llm_answer(question, enriched)

        return {
            "ok": True,
            "question": question,
            "count": len(enriched),
            "results": enriched,
            "context": context,
            "answer": answer,
        }

    def _llm_answer(self, question: str, results: List[Dict]) -> Optional[str]:
        """Generate an answer from context."""
        try:
            from novamind.core.providers.orchestrator import orchestrator
        except ImportError:
            return None

        # Build context from actual code
        context_parts = []
        for r in results[:5]:
            text = r.get("text", "")[:500]
            context_parts.append(text)

        context = "\n\n---\n\n".join(context_parts)

        prompt = f"""لديك سياق من قاعدة كود Python:

{context}

السؤال: {question}

أجب بالعربية بناءً على السياق فقط."""

        try:
            result = orchestrator.call(prompt, task="smart", max_tokens=500)
            if result.get("ok"):
                return result.get("text", "")
        except Exception as e:
            logger.warning(f"LLM answer failed: {e}")
        return None

    def find_similar(self, code: str, limit: int = 5) -> Dict:
        """Find similar code."""
        store = self._get_store()
        results = store.search(code, limit=limit)
        return {"ok": True, "similar": results, "count": len(results)}

    def find_related(self, node_id: str, depth: int = 2) -> Dict:
        """Find related via KG."""
        kg = self._get_kg()
        subgraph = kg.subgraph(node_id, depth=depth)

        return {
            "ok": True,
            "node_id": node_id,
            "nodes": subgraph["nodes"],
            "edges": subgraph["edges"],
            "total_nodes": len(subgraph["nodes"]),
            "total_edges": len(subgraph["edges"]),
        }

    def trace_call_chain(self, from_fn: str, to_fn: str,
                          max_depth: int = 5) -> Dict:
        """Find call chain."""
        kg = self._get_kg()
        path = kg.find_path(from_fn, to_fn, max_depth=max_depth)

        return {
            "ok": path is not None,
            "from": from_fn,
            "to": to_fn,
            "path": path,
            "hops": len(path) - 1 if path else 0,
        }

    def stats(self) -> Dict:
        store = self._get_store()
        kg = self._get_kg()
        return {
            "vector_store": store.stats(),
            "knowledge_graph": kg.stats(),
        }


rag_agent = RAGAgent()
__all__ = ["RAGAgent", "rag_agent"]
