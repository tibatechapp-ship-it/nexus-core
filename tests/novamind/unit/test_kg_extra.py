"""Extra KnowledgeGraph tests."""
from novamind.core.rag.knowledge_graph import KnowledgeGraph


def test_kg_path_finding():
    """Graph should find paths."""
    kg = KnowledgeGraph("ci_test_path")
    kg.clear()
    kg.add_edge("a", "b", "x")
    kg.add_edge("b", "c", "x")
    path = kg.find_path("a", "c")
    assert path == ["a", "b", "c"]
    kg.clear()


def test_kg_stats():
    """Graph stats should work."""
    kg = KnowledgeGraph("ci_test_stats")
    kg.clear()
    kg.add_node("n1", "type1")
    kg.add_node("n2", "type2")
    s = kg.stats()
    assert s["total_nodes"] == 2
    kg.clear()
