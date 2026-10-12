"""
Test: Agent Registry — verify all 52 agents are registered.
"""
import pytest


EXPECTED_AGENT_COUNT = 79


class TestAgentRegistry:
    """Verify the agent registry is complete and consistent."""

    def test_total_count(self, factory, expected_agent_count):
        """There must be exactly 52 agents registered."""
        agents = factory.list_all()
        assert len(agents) == expected_agent_count, \
            f"Expected {expected_agent_count}, got {len(agents)}"

    def test_all_available(self, factory, available_agent_names):
        """All registered agents should be available."""
        available = factory.list_available()
        # نستخدم عدد nova._registry — لا عدد ثابت
        from novamind.registry import all_agent_names
        expected = len(all_agent_names())
        assert len(available) == expected, \
            f"Only {len(available)}/{expected} available"

    def test_no_duplicates(self, factory):
        """Agent names must be unique."""
        agents = factory.list_all()
        assert len(agents) == len(set(agents)), "Duplicate agent names!"

    def test_all_agents_instantiable(self, factory, available_agent_names):
        """Every agent must be gettable from the factory."""
        for name in available_agent_names:
            agent = factory.get(name)
            assert agent is not None, f"Agent '{name}' returned None"

    def test_each_agent_has_main_method(self, factory, available_agent_names):
        """Each tool agent should have its registered main method.
        Managers may have main_function=None.
        """
        for name in available_agent_names:
            role = factory.get_role(name)
            if role != "tool":
                continue
            agent = factory.get(name)
            _, _, method_name = factory.REGISTRY[name]
            assert method_name is not None, f"{name}: main_function is None (tool)"
            method = getattr(agent, method_name, None)
            assert method is not None, f"{name}: method {method_name} is None"

    def test_stats_consistent(self, factory):
        """Factory stats should be consistent."""
        stats = factory.stats()
        from novamind.registry import all_agent_names
        expected = len(all_agent_names())
        assert stats["total_registered"] == expected, \
            f"stats: {stats['total_registered']} != registry: {expected}"
