"""Tests for src/skills/loader.py — SKILL.md-based skill system."""

from __future__ import annotations

from pathlib import Path

from src.skills.loader import DEFAULT_SKILLS, SEED_DIR, Skill, SkillLoader


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


def test_a_skill_without_a_heading_has_an_empty_description(tmp_path: Path) -> None:
    """A body with no ``#`` line leaves the description empty (no crash)."""
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "SKILL.md").write_text("rules only\nmore rules\n", encoding="utf-8")
    skill = SkillLoader(base_dir=tmp_path).load("plain")
    assert skill is not None
    assert skill.description == ""


def test_search_matches_name_and_content(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    by_name = sl.search("security")
    assert [s.name for s in by_name] == ["security-audit"]
    by_content = sl.search("XSS")  # appears only in the security-audit body
    assert "security-audit" in [s.name for s in by_content]
    assert sl.search("zzz-not-present") == []


#────────────────────── seed dir + user override (layer 3) ──────────────────────#


def test_seed_dir_populates_only_the_seed_when_given(tmp_path: Path) -> None:
    """With a seed dir, the shipped skills land there — not in the user dir."""
    seed = tmp_path / "seed"
    sl = SkillLoader(base_dir=tmp_path / "user", seed_dir=seed)
    assert (seed / "code-review" / "SKILL.md").exists()
    assert sl.list_skills() == sorted(DEFAULT_SKILLS)
    assert not (tmp_path / "user" / "code-review").exists()


def test_user_skill_overrides_the_seed(tmp_path: Path) -> None:
    """A user skill with the same name wins over the shipped seed."""
    seed = tmp_path / "seed"
    user = tmp_path / "user"
    sl = SkillLoader(base_dir=user, seed_dir=seed)
    (user / "code-review").mkdir(parents=True)
    (user / "code-review" / "SKILL.md").write_text(
        "# My Own Review\n\ncustom rules\n", encoding="utf-8"
    )
    skill = sl.load("code-review")
    assert skill is not None
    assert skill.description == "My Own Review"
    assert skill.content == "# My Own Review\n\ncustom rules\n"


def test_user_only_skill_is_listed(tmp_path: Path) -> None:
    """The list is the union of the seed and the user dir."""
    seed = tmp_path / "seed"
    user = tmp_path / "user"
    sl = SkillLoader(base_dir=user, seed_dir=seed)
    (user / "my-skill").mkdir(parents=True)
    (user / "my-skill" / "SKILL.md").write_text("# Mine\n", encoding="utf-8")
    names = sl.list_skills()
    assert "my-skill" in names
    assert "code-review" in names  # still from the seed


def test_sources_lists_the_read_dirs(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    user = tmp_path / "user"
    sl = SkillLoader(base_dir=user, seed_dir=seed)
    assert sl.sources() == [str(user), str(seed)]


def test_sources_without_a_seed_dir_is_only_the_base(tmp_path: Path) -> None:
    sl = SkillLoader(base_dir=tmp_path)
    assert sl.sources() == [str(tmp_path)]


def test_repo_seed_dir_ships_the_default_skills() -> None:
    """The in-repo ``skills/`` seed carries the shipped set."""
    assert SEED_DIR.is_dir()
    assert set(SkillLoader(seed_dir=SEED_DIR).list_skills()) >= set(DEFAULT_SKILLS)
