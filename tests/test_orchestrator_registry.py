"""Registry tests."""
import json
import pytest
from src.orchestrator.registry import AgentRegistry, RegistryError


def test_registry_matches_manifest():
    from src.agents.manifest import all_manifests
    reg = AgentRegistry(manifests=all_manifests())
    assert len(reg) == len(all_manifests()) == 20


def test_rejects_missing_manifest(tmp_path):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"agents": {
        "coder": {"domain": "x", "scope": [], "input_schema": {}, "output_schema": {}}
    }}))
    with pytest.raises(RegistryError, match="missing from registry"):
        AgentRegistry(p, manifests={"coder": {}, "tester": {}})


def test_rejects_extra_in_registry(tmp_path):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"agents": {
        "coder": {"domain": "x", "scope": [], "input_schema": {}, "output_schema": {}},
        "ghost": {"domain": "x", "scope": [], "input_schema": {}, "output_schema": {}},
    }}))
    with pytest.raises(RegistryError, match="not in manifest"):
        AgentRegistry(p, manifests={"coder": {}})


def test_in_domain_returns_members():
    reg = AgentRegistry()
    assert "tester" in reg.in_domain("engineering.testing")


def test_get_unknown_raises():
    reg = AgentRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent_agent")
