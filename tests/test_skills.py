"""Tests for src/skills/loader.py — SKILL.md-based skill system."""

from __future__ import annotations

from pathlib import Path

from src.skills.loader import Skill, SkillLoader


def test_seeds_default_skills(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    names = sl.list_skills()
    assert "code-review" in names
    assert "security-audit" in names
    assert (tmp_path / "code-review" / "SKILL.md").exists()


def test_seed_is_idempotent(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    sl._seed_defaults()  # second call must not overwrite/recreate
    assert (tmp_path / "testing" / "SKILL.md").exists()


def test_list_skips_non_skill_dirs_and_files(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    (tmp_path / "no-markdown").mkdir()
    (tmp_path / "loose.txt").write_text("x", encoding="utf-8")
    names = sl.list_skills()
    assert "no-markdown" not in names
    assert "loose.txt" not in names


def test_load_returns_skill_with_description(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    skill = sl.load("code-review")
    assert isinstance(skill, Skill)
    assert skill.description == "Code Review Skill"
    assert skill.path.name == "SKILL.md"


def test_load_missing_returns_none(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    assert sl.load("does-not-exist") is None


def test_search_matches_name_and_content(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    by_name = sl.search("security")
    assert [s.name for s in by_name] == ["security-audit"]
    by_content = sl.search("XSS")  # appears only in the security-audit body
    assert "security-audit" in [s.name for s in by_content]
    assert sl.search("zzz-not-present") == []
