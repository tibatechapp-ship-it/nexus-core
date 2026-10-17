"""Tests for the agent manifest suite (P1 of the agent-training plan).

Covers the two P1 criteria — 20/20 agents have a valid manifest, and a
malformed manifest fails loudly — plus the identity single-sourcing rule.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from src.agents import AGENT_CLASSES
from src.agents.base import BaseAgent
from src.agents.manifest import (
    KNOWN_ADVERSARIAL,
    KNOWN_GATES,
    KNOWN_SKILLS,
    KNOWN_TOOLS,
    AgentManifest,
    ManifestError,
    all_manifests,
    build_manifests,
    get_manifest,
    manifest_problems,
    validate_suite,
)


def _valid() -> AgentManifest:
    """A known-good manifest to mutate in the negative tests."""
    return all_manifests()["coder"]


# -- the happy path (P1 criterion: 20/20) ---------------------------------


def test_one_manifest_per_builtin_agent() -> None:
    manifests = all_manifests()
    assert len(manifests) == len(AGENT_CLASSES) == 20
    assert set(manifests) == {cls.name for cls in AGENT_CLASSES}


def test_whole_suite_is_valid() -> None:
    for manifest in validate_suite().values():
        assert manifest_problems(manifest) == ()


def test_manifest_projects_the_agent_class() -> None:
    """The class is the single source of identity — no drift possible."""
    for cls in AGENT_CLASSES:
        manifest = get_manifest(cls.name)
        assert manifest.id == cls.name
        assert manifest.group == cls.group
        assert manifest.identity == cls.system_prompt
        assert manifest.tools == tuple(cls.tools)
        assert manifest.memory_scope == f"agent:{cls.name}"


def test_tools_and_skills_are_known_vocabulary() -> None:
    for manifest in all_manifests().values():
        assert set(manifest.tools) <= KNOWN_TOOLS
        assert set(manifest.skills) <= KNOWN_SKILLS
        assert set(manifest.gates) <= KNOWN_GATES
        assert set(manifest.adversarial) <= KNOWN_ADVERSARIAL


def test_tools_required_is_derived_from_mutating_tools() -> None:
    manifests = all_manifests()
    assert manifests["coder"].tools_required is True  # write/bash/edit
    assert manifests["architect"].tools_required is True  # write
    assert manifests["analyst"].tools_required is False  # read/search only
    assert manifests["reviewer"].tools_required is False


def test_manifest_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _valid().title = "mutated"  # type: ignore[misc]


def test_to_dict_is_json_friendly() -> None:
    payload = _valid().to_dict()
    assert isinstance(payload["tools"], list)
    json.dumps(payload)  # must not raise


def test_get_manifest_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        get_manifest("does-not-exist")


# -- negative cases (P1 criterion: malformed fails) -----------------------


@pytest.mark.parametrize("field", ["title", "spec", "identity", "memory_scope"])
def test_empty_field_is_reported(field: str) -> None:
    manifest = dataclasses.replace(_valid(), **{field: "  "})
    problems = manifest_problems(manifest)
    assert any(field in problem for problem in problems)


def test_unknown_tool_fails() -> None:
    bad = dataclasses.replace(_valid(), tools=("read", "time-travel"))
    assert any("unknown tools" in p for p in manifest_problems(bad))


def test_unknown_tool_is_rejected_by_build() -> None:
    class _Rogue(BaseAgent):  # pragma: no cover - only the metadata matters
        name = "rogue"
        tools = ("nonsense",)

    with pytest.raises(ManifestError):
        build_manifests([_Rogue])


def test_duplicate_tools_are_a_problem() -> None:
    bad = dataclasses.replace(_valid(), tools=("read", "read"))
    assert any("duplicate tools" in p for p in manifest_problems(bad))


def test_unknown_skill_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), skills=("telepathy",))
    assert any("unknown skills" in p for p in manifest_problems(bad))


def test_duplicate_skills_are_a_problem() -> None:
    bad = dataclasses.replace(_valid(), skills=("testing", "testing"))
    assert any("duplicate skills" in p for p in manifest_problems(bad))


def test_invalid_id_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), id="Coder")
    assert any("invalid id" in p for p in manifest_problems(bad))


def test_missing_gates_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), gates=())
    assert any("no gates" in p for p in manifest_problems(bad))


def test_unknown_gate_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), gates=("vibes",))
    assert any("unknown gates" in p for p in manifest_problems(bad))


def test_unknown_adversarial_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), adversarial=("mind-reading",))
    assert any("unknown adversarial" in p for p in manifest_problems(bad))


def test_duplicate_adversarial_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), adversarial=("xss", "xss"))
    assert any("duplicate adversarial" in p for p in manifest_problems(bad))


def test_tools_required_without_tools_is_a_problem() -> None:
    bad = dataclasses.replace(_valid(), tools=(), tools_required=True)
    assert any("tools_required" in p for p in manifest_problems(bad))


# -- suite-level guards ----------------------------------------------------


def test_missing_extra_row_raises() -> None:
    class _Unknown(BaseAgent):
        name = "ghost"
        tools = ("read",)

    with pytest.raises(ManifestError, match="no _EXTRAS row"):
        build_manifests([*AGENT_CLASSES, _Unknown])


def test_subset_agent_list_reports_orphan_rows() -> None:
    """Passing a subset is a real error, not a silent partial suite."""
    with pytest.raises(ManifestError, match="orphan _EXTRAS rows"):
        build_manifests(list(AGENT_CLASSES)[:3])


def test_validate_suite_rejects_a_truncated_list() -> None:
    with pytest.raises(ManifestError):
        validate_suite(list(AGENT_CLASSES)[:-1])


def test_get_manifest_unknown_agent_raises_keyerror() -> None:
    with pytest.raises(KeyError, match="no manifest for agent 'nope'"):
        get_manifest("nope")


def test_manifests_are_immutable() -> None:
    manifest = _valid()
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.id = "changed"  # type: ignore[misc]


def test_to_dict_round_trips_the_suite() -> None:
    payload = json.dumps(
        {mid: m.to_dict() for mid, m in all_manifests().items()},
        ensure_ascii=False,
    )
    assert json.loads(payload)["coder"]["title"] == "المهندس المبرمج"
