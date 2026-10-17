"""Tests for ``src/skills/inject.py`` — skills-first prompt injection (layer 3).

Hermetic: temp skill dirs, no home touch, no network. The manifest is the single
source of *which* skills an agent has, so one test drives injection through a
real built-in agent id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.skills.inject import (
    DEFAULT_LIMIT,
    agent_skill_names,
    get_skill_loader,
    inject_skills_into_prompt,
    load_skills,
    render_skills,
    reset_skill_loader,
    skills_block,
)
from src.skills.loader import Skill, SkillLoader

_HEADER = "### المهارات المُفعَّلة (Skills)"


#────────────────────────────── fixtures ──────────────────────────────#


@pytest.fixture()
def loader(tmp_path: Path) -> SkillLoader:
    """A loader whose seed dir holds two real skills."""
    seed = tmp_path / "seed"
    sl = SkillLoader(base_dir=tmp_path / "user", seed_dir=seed)
    (seed / "alpha").mkdir(parents=True, exist_ok=True)
    (seed / "beta").mkdir(parents=True, exist_ok=True)
    (seed / "alpha" / "SKILL.md").write_text("# Alpha Skill\n\nrules a\n", encoding="utf-8")
    (seed / "beta" / "SKILL.md").write_text("# Beta Skill\n\nrules b\n", encoding="utf-8")
    return sl


@pytest.fixture(autouse=True)
def _clean_singleton() -> Any:
    """Keep the module singleton from leaking between tests."""
    reset_skill_loader()
    yield
    reset_skill_loader()


#────────────────────────────── loader helpers ──────────────────────────────#


def test_load_skills_skips_unknown(loader: SkillLoader) -> None:
    found = load_skills(("alpha", "nope", "beta"), loader=loader)
    assert [s.name for s in found] == ["alpha", "beta"]


def test_render_skills_empty_is_empty_string() -> None:
    assert render_skills([]) == ""


def test_render_skills_lists_names_and_bodies(loader: SkillLoader) -> None:
    skills = load_skills(("alpha",), loader=loader)
    text = render_skills(skills)
    assert _HEADER in text
    assert "<!-- skills: alpha -->" in text
    assert "Alpha Skill" in text
    assert "rules a" in text


#────────────────────────────── which skills ──────────────────────────────#


def test_agent_skill_names_from_a_manifest_like_object() -> None:
    class _Manifest:
        skills = ("code-review", "testing")

    assert agent_skill_names(_Manifest()) == ("code-review", "testing")


def test_agent_skill_names_reads_the_real_manifest() -> None:
    """A built-in agent id resolves to its manifest skills (single source)."""
    from src.agents.manifest import get_manifest

    assert agent_skill_names("coder") == get_manifest("coder").skills


def test_agent_skill_names_unknown_agent_is_empty() -> None:
    assert agent_skill_names("does-not-exist") == ()
    assert agent_skill_names("") == ()
    assert agent_skill_names(None) == ()


#────────────────────────────── the block ──────────────────────────────#


def test_skills_block_injects_only_existing_skills(loader: SkillLoader) -> None:
    class _Manifest:
        skills = ("alpha", "missing", "beta")

    block = skills_block(_Manifest(), loader=loader)
    assert "alpha" in block
    assert "beta" in block
    assert "missing" not in block


def test_limits_the_number_of_skills(loader: SkillLoader) -> None:
    class _Manifest:
        skills = ("alpha", "beta")

    block = skills_block(_Manifest(), loader=loader, limit=1)
    assert "alpha" in block
    assert "beta" not in block


def test_zero_limit_yields_empty(loader: SkillLoader) -> None:
    class _Manifest:
        skills = ("alpha",)

    assert skills_block(_Manifest(), loader=loader, limit=0) == ""


def test_no_skills_yields_empty_block(loader: SkillLoader) -> None:
    class _Manifest:
        skills: tuple[str, ...] = ()

    assert skills_block(_Manifest(), loader=loader) == ""


#────────────────────────────── composition ──────────────────────────────#


def test_inject_appends_the_block_after_instructions(loader: SkillLoader) -> None:
    class _Manifest:
        skills = ("alpha",)

    text = inject_skills_into_prompt("You are A.", _Manifest(), loader=loader)
    assert text.startswith("You are A.")
    assert _HEADER in text


def test_inject_returns_instructions_unchanged_without_skills(loader: SkillLoader) -> None:
    class _Manifest:
        skills: tuple[str, ...] = ()

    assert inject_skills_into_prompt("  hi  ", _Manifest(), loader=loader) == "hi"


def test_inject_without_instructions_returns_block_only(loader: SkillLoader) -> None:
    class _Manifest:
        skills = ("alpha",)

    text = inject_skills_into_prompt("", _Manifest(), loader=loader)
    assert text.startswith(_HEADER)


def test_default_limit_constant_is_positive() -> None:
    assert DEFAULT_LIMIT >= 1


#────────────────────────────── singleton ──────────────────────────────#


def test_get_skill_loader_is_a_singleton() -> None:
    assert get_skill_loader() is get_skill_loader()


def test_reset_skill_loader_rebuilds() -> None:
    first = get_skill_loader()
    reset_skill_loader()
    assert get_skill_loader() is not first


def test_skill_is_a_dataclass() -> None:
    skill = Skill(name="x", description="d", content="c", path=Path("/tmp/x"))
    assert skill.name == "x"
