"""Regression tests for the single NovaMind registry and RBAC authority."""
from __future__ import annotations

import pytest

from novamind.core.hive.core import agents_registry as hive_registry
from novamind.core.hive.factory.guards import can_agent_use_tool
from novamind.registry import can_use_tool, get_agent, has_permission
from novamind.security.permissions import get_permissions, get_role_for_agent


def test_canonical_registry_resolves_real_agents() -> None:
    coder = get_agent("coder")

    assert coder["module"] == "novamind.agents.coder"
    assert coder["category"] == "code"
    assert get_agent("code_review")["category"] == "code"


def test_known_agent_permissions_are_category_and_role_scoped() -> None:
    assert has_permission("coder", "write_code")
    assert has_permission("coder", "run_tests")
    assert not has_permission("code_review", "write_code")
    assert has_permission("code_review", "review_code")
    assert get_role_for_agent("code_review") == "quality"


def test_unknown_agents_receive_no_implicit_permissions() -> None:
    assert get_role_for_agent("not-a-registered-agent") == "unknown"
    assert get_permissions("not-a-registered-agent") == []
    assert not has_permission("not-a-registered-agent", "write_code")
    assert not can_use_tool("not-a-registered-agent", "run_tests")
    with pytest.raises(KeyError):
        get_agent("not-a-registered-agent")


def test_legacy_hive_registry_is_an_adapter_not_a_mock_registry() -> None:
    coder = hive_registry.get_agent("coder")

    assert coder["name"] == "coder"
    assert coder["permissions"] == get_permissions("coder")
    assert coder["permissions"]
    with pytest.raises(KeyError):
        hive_registry.get_agent("not-a-registered-agent")


def test_all_authorization_entrypoints_share_the_same_decision() -> None:
    cases = [
        ("coder", "write_code"),
        ("code_review", "write_code"),
        ("code_review", "review_code"),
        ("not-a-registered-agent", "write_code"),
    ]
    for agent, permission in cases:
        expected = has_permission(agent, permission)
        assert can_use_tool(agent, permission) is expected
        assert can_agent_use_tool(agent, permission) is expected


def test_missing_canonical_registry_never_falls_back_to_v2(monkeypatch) -> None:
    import novamind.registry as registry_api

    monkeypatch.setattr(registry_api, "_CORE_AVAILABLE", False)

    assert registry_api.validate() == [
        "canonical NovaMind registry is unavailable"
    ]
    assert not registry_api.has_permission("coder", "write_code")
    assert not registry_api.can_use_tool("coder", "write_code")
    with pytest.raises(RuntimeError, match="canonical NovaMind registry"):
        registry_api.get_agent("coder")
    with pytest.raises(RuntimeError, match="canonical NovaMind registry"):
        registry_api.all_agent_names()
    with pytest.raises(RuntimeError, match="canonical NovaMind registry"):
        registry_api.stats()
