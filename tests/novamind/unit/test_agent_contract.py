"""
Test: Agent Contract v3
- كل وكيل يحمل name
- كل tool agent لديه method قابل للاستدعاء
- manager agents: name فقط (قد لا يكون لها method)
"""
import pytest


class TestAgentContract:

    def test_all_agents_have_name_attr(self, factory, available_agent_names):
        """كل وكيل يحمل name."""
        missing = []
        for name in available_agent_names:
            agent = factory.get(name)
            assert agent is not None, f"{name}: factory.get() → None"
            if not hasattr(agent, "name"):
                missing.append(name)
        assert not missing, (
            f"{len(missing)} بلا name من {len(available_agent_names)}: {missing[:10]}"
        )

    def test_every_agent_loads(self, factory, available_agent_names):
        """كل وكيل يُحمَّل."""
        failures = []
        for name in available_agent_names:
            try:
                if factory.get(name) is None:
                    failures.append((name, "None"))
            except Exception as e:
                failures.append((name, f"{type(e).__name__}: {e}"))
        assert not failures, f"{len(failures)} فشل: {failures[:10]}"

    def test_tools_have_main_method(self, factory, available_agent_names):
        """كل tool agent له main_method."""
        failures = []
        for name in available_agent_names:
            role = factory.get_role(name)
            if role != "tool":
                continue
            try:
                agent = factory.get(name)
                method = factory.REGISTRY[name][2]
                if not method:
                    failures.append((name, "main_function=None"))
                elif not hasattr(agent, method):
                    failures.append((name, f"missing {method}"))
            except Exception as e:
                failures.append((name, str(e)[:60]))
        assert not failures, f"{len(failures)} tools فشلت: {failures[:10]}"

    def test_managers_have_identity(self, factory, available_agent_names):
        """كل manager له name + على الأقل method واحد أو __call__."""
        failures = []
        for name in available_agent_names:
            role = factory.get_role(name)
            if role != "manager":
                continue
            try:
                agent = factory.get(name)
                if not hasattr(agent, "name"):
                    failures.append((name, "no .name"))
                # manager يجب أن يكون له على الأقل __call__ أو method
                if not callable(agent):
                    methods = [m for m in dir(agent) if not m.startswith("_")]
                    if not methods:
                        failures.append((name, "no callable or methods"))
            except Exception as e:
                failures.append((name, str(e)[:60]))
        assert not failures, f"{len(failures)} managers فشلت: {failures[:10]}"

    def test_no_circular_imports(self, factory, available_agent_names):
        failures = []
        for name in available_agent_names:
            try:
                factory.get(name)
            except ImportError as e:
                failures.append((name, str(e)[:80]))
        assert not failures, f"Circular imports: {failures[:10]}"

    def test_all_aliases_resolve(self, factory):
        from novamind.registry import alias_index
        failures = []
        for alias, canonical in alias_index().items():
            try:
                if factory.get(alias) is None:
                    failures.append((alias, "get(alias)=None"))
                if factory.get(canonical) is None:
                    failures.append((canonical, "get(canonical)=None"))
            except Exception as e:
                failures.append((alias, str(e)[:60]))
        assert not failures, f"aliases: {failures[:10]}"

    def test_factory_call_unknown_agent(self, factory):
        result = factory.call("nonexistent_agent_xyz", code="x=1")
        assert isinstance(result, dict)
        assert "error" in result
        if "ok" in result:
            assert result["ok"] is False
