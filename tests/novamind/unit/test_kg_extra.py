"""Extra KnowledgeGraph tests — isolated via tmp_path.

KnowledgeGraph writes JSON to KG_DIR/{name}.json. KG_DIR is a module
global pointing into the source tree, so tests using literal names
('ci_test_path', 'ci_test_stats', ...) leaked artifacts under
src/memory/knowledge_graph/ — invisible to 'make check' because it
excludes tests/novamind.

Fix: autouse fixture redirects KG_DIR to a per-test tmp_path.
"""
import pytest

from novamind.core.rag import knowledge_graph as kgmod
from novamind.core.rag.knowledge_graph import KnowledgeGraph


@pytest.fixture(autouse=True)
def _isolate_kg_dir(tmp_path, monkeypatch):
    """Redirect KG_DIR to a per-test temp dir (auto-cleaned by pytest)."""
    monkeypatch.setattr(kgmod, "KG_DIR", tmp_path)


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
