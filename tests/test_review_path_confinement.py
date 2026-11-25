"""Regression tests for review file path confinement."""

from pathlib import Path

import pytest

from src.security.path_confinement import is_safe_regular_file


def test_accepts_regular_file_inside_selected_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    source = root / "module.py"
    source.write_text("safe = True\n", encoding="utf-8")

    assert is_safe_regular_file(root, source) is True


def test_rejects_file_outside_selected_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "private.py"
    outside.write_text("secret = 'not for model context'\n", encoding="utf-8")

    assert is_safe_regular_file(root, outside) is False


def test_rejects_symlink_to_file_outside_selected_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "private.py"
    outside.write_text("secret = 'not for model context'\n", encoding="utf-8")
    link = root / "ordinary_name.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not supported on this platform")

    assert is_safe_regular_file(root, link) is False


def test_rejects_symlink_even_when_target_is_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "real.py"
    target.write_text("safe = True\n", encoding="utf-8")
    link = root / "alias.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not supported on this platform")

    assert is_safe_regular_file(root, link) is False
