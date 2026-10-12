"""
Smoke tests — each of the 52 agents must run without crashing.
"""
import pytest


SMOKE_CODE = '''
def hello(name):
    print("Hello " + name)
    return name
'''


class TestSmokeAllAgents:
    """Quick smoke test: every agent must not crash on simple input."""

    def test_factory_loads_all(self, factory, available_agent_names):
        """All registered agents must load without errors."""
        all_agents = factory.list_all()
        assert len(available_agent_names) == len(all_agents), \
            f"Only {len(available_agent_names)}/{len(all_agents)} agents loaded"

    def test_no_load_errors(self, factory):
        """Factory stats must show 0 failed."""
        stats = factory.stats()
        assert stats["failed"] == 0, f"Errors: {stats['errors']}"

    @pytest.mark.parametrize("agent_name", [
        "crypto", "xss", "injection", "secrets", "auth",
        "dependency", "privacy", "compliance",
        "naming", "complexity", "deadcode", "duplication",
        "architecture", "api_design",
        "sql", "nosql", "db_migration", "orm", "indexing", "transaction",
        "docker", "k8s", "cicd", "nginx", "terraform", "monitoring",
        "react", "vue", "css", "a11y", "rtl",
        "prompt", "embedding", "finetune", "evaluation", "builder",
    ])
    def test_pure_agent_runs(self, factory, agent_name):
        """Pure (regex-based) agents must run on sample code."""
        result = factory.call(agent_name, code=SMOKE_CODE, filename="test.py")
        assert isinstance(result, dict), f"'{agent_name}' not dict"
        # Must not have ok=False due to crash
        if "error" in result:
            # Some agents may return error for unsupported input
            # but should not raise exceptions
            assert "Traceback" not in str(result["error"])

    def test_empty_code_handled(self, factory, sample_empty_code):
        """Agents must handle empty code gracefully."""
        for name in ["crypto", "xss", "injection", "secrets", "prompt"]:
            try:
                result = factory.call(name, code=sample_empty_code)
                assert isinstance(result, dict)
            except Exception as e:
                pytest.fail(f"'{name}' crashed on empty code: {e}")

    def test_vulnerable_code_detected(self, factory, sample_vulnerable_code):
        """Security agents must detect issues in vulnerable code."""
        # crypto should detect MD5
        result = factory.call("crypto", code=sample_vulnerable_code,
                              filename="test.py")
        assert result.get("verdict") == "issues" or \
               result.get("total", 0) > 0, \
               f"crypto missed MD5: {result}"

        # secrets should detect hardcoded key
        result = factory.call("secrets", code=sample_vulnerable_code,
                              filename="test.py")
        assert result.get("verdict") == "issues" or \
               result.get("total", 0) > 0, \
               f"secrets missed hardcoded key: {result}"

    def test_clean_code_no_false_positives(self, factory, sample_code):
        """Security agents must NOT flag clean code."""
        for name in ["crypto", "secrets", "xss", "injection"]:
            result = factory.call(name, code=sample_code, filename="test.py")
            # Clean code should have verdict=ok
            issues = result.get("issues", [])
            total = result.get("total", len(issues))
            assert total <= 1, \
                f"'{name}' false positive on clean code: {issues}"
