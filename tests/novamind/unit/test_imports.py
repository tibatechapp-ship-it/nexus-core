"""Basic import tests — verify all modules load."""
import pytest


def test_can_import_agents():
    """Test that agents import correctly."""
    from novamind.agents.security_agent import security_agent
    from novamind.agents.performance_agent import performance_agent
    from novamind.agents.documentation_agent import documentation_agent
    from novamind.agents.refactor_agent import refactor_agent
    from novamind.agents.code_review_agent import code_review_agent
    from novamind.agents.migration_agent import migration_agent
    assert security_agent is not None
    assert performance_agent is not None


def test_can_import_rag():
    """Test that RAG modules import correctly."""
    from novamind.core.rag.vector_store import VectorStore
    from novamind.core.rag.knowledge_graph import KnowledgeGraph
    assert VectorStore is not None
    assert KnowledgeGraph is not None


def test_can_import_orchestrator():
    """Test orchestrator imports."""
    from novamind.core.agent_orchestrator import agent_orchestrator
    assert agent_orchestrator is not None
