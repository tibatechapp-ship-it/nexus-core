"""Test RAG modules."""
import pytest


def test_vector_store_add_search():
    """VectorStore should store and search."""
    from novamind.core.rag.vector_store import VectorStore
    vs = VectorStore("ci_test")
    vs.clear()
    vs.add("def authenticate user password")
    vs.add("def calculate total items")
    results = vs.search("password", limit=1)
    assert len(results) > 0
    vs.clear()


def test_kg_add_edge():
    """KnowledgeGraph should add edges."""
    from novamind.core.rag.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph("ci_test")
    kg.clear()
    kg.add_edge("a", "b", "test")
    assert "b" in kg.get_neighbors("a")
    kg.clear()
