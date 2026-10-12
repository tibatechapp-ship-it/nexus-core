"""A2A Protocol — Agent-to-Agent communication."""
from novamind.core.a2a.agent_card import AgentCard, AgentSkill, A2A_VERSION
from novamind.core.a2a.server import A2AServer, create_app
from novamind.core.a2a.client import A2AClient

__all__ = [
    "AgentCard", "AgentSkill", "A2A_VERSION",
    "A2AServer", "create_app",
    "A2AClient",
]
