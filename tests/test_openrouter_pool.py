"""Tests for OpenRouter key pool loading and failover (11 keys)."""
import os
import time


def _load_openrouter_keys(env: dict) -> dict:
    """Replicate the LLMOrchestrator OpenRouter loading loop."""
    apps = {}
    for i in range(1, 12):
        key = env.get(f"OPENROUTER_API_KEY_{i}", "").strip()
        if key and len(key) > 10:
            apps[f"openrouter-{i}"] = {"name": f"openrouter-{i}", "priority": 25 + i}
    return apps


class TestOpenRouterKeyLoading:
    def test_11_keys_load_11_apps(self):
        env = {f"OPENROUTER_API_KEY_{i}": f"sk-or-v1-test{i:040d}" for i in range(1, 12)}
        apps = _load_openrouter_keys(env)
        assert len(apps) == 11
        assert "openrouter-11" in apps

    def test_10_keys_load_10_apps(self):
        env = {f"OPENROUTER_API_KEY_{i}": f"sk-or-v1-test{i:040d}" for i in range(1, 11)}
        apps = _load_openrouter_keys(env)
        assert len(apps) == 10
        assert "openrouter-11" not in apps

    def test_no_keys_no_crash(self):
        apps = _load_openrouter_keys({})
        assert len(apps) == 0

    def test_partial_keys_load_correctly(self):
        env = {"OPENROUTER_API_KEY_1": "sk-or-v1-abc", "OPENROUTER_API_KEY_11": "sk-or-v1-xyz"}
        apps = _load_openrouter_keys(env)
        assert len(apps) == 2
        assert "openrouter-1" in apps
        assert "openrouter-11" in apps


class TestOpenRouterFailover:
    def test_key_11_selected_when_1_to_10_unhealthy(self):
        """Simulate 11 apps, mark first 10 unhealthy, verify key 11 is first healthy."""
        env = {f"OPENROUTER_API_KEY_{i}": f"sk-or-v1-test{i:040d}" for i in range(1, 12)}
        apps = _load_openrouter_keys(env)
        # Simulate health: first 10 unhealthy, key 11 healthy
        health = {name: (name != "openrouter-11") for name in apps}  # True = unhealthy
        # Sort by priority (25+i)
        sorted_apps = sorted(apps.values(), key=lambda a: a["priority"])
        # Find first healthy
        first_healthy = None
        for app in sorted_apps:
            if not health[app["name"]]:
                first_healthy = app
                break
        assert first_healthy is not None
        assert first_healthy["name"] == "openrouter-11", (
            f"Expected openrouter-11, got {first_healthy['name']}"
        )
