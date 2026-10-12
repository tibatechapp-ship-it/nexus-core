"""Extra vector store tests."""
from novamind.core.rag.vector_store import VectorStore


def test_vs_handles_arabic():
    """VectorStore should handle Arabic text."""
    vs = VectorStore("ci_test_ar")
    vs.clear()
    vs.add("نص عربي في ملف")
    results = vs.search("عربي", limit=1)
    assert len(results) > 0
    vs.clear()


def test_vs_empty_search():
    """Empty search should return empty."""
    vs = VectorStore("ci_test_empty")
    vs.clear()
    results = vs.search("nothing", limit=1)
    assert results == []
