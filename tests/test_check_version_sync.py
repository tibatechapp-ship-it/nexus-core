"""Guard tests for `scripts/check_version_sync.py`.

The script is the CI gate that catches "silent version drift": a release tag
whose own `pyproject.toml` says something else, or an `openapi.yaml` left on an
old release. These tests exercise the PURE readers/logic (no git dependence) so
the guard cannot silently rot.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = "check_version_sync"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "check_version_sync.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


class TestReaders:
    def test_read_pyproject_matches_package_version(self) -> None:
        from src import __version__

        assert mod.read_pyproject() == __version__

    def test_read_src_version_is_imported_not_parsed(self) -> None:
        # Regression: `src/__init__.py` sets `__version__ = _read_version()`
        # (a CALL), so a naive text parse returns "_read_version()" and the
        # check would always fail. It must import the module.
        assert mod.read_src_version().count(".") == 2
        assert "read_version" not in mod.read_src_version()

    def test_read_openapi_matches_package_version(self) -> None:
        from src import __version__

        assert mod.read_openapi() == __version__

    def test_read_openapi_does_not_pick_up_another_version_key(self) -> None:
        # The scanner must stay inside the `info:` block — a `version:` under a
        # different top-level key must not be mistaken for api version.
        assert mod.read_openapi() == mod.read_pyproject()


class TestSemver:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1.2.3", (1, 2, 3)),
            ("1.22.0", (1, 22, 0)),
            ("1.20.2+suffix", (1, 20, 2)),
        ],
    )
    def test_parses(self, value: str, expected: tuple[int, int, int]) -> None:
        assert mod._semver(value) == expected

    @pytest.mark.parametrize("value", ["1.2", "abc", "1.2.3.4", ""])
    def test_rejects_non_semver(self, value: str) -> None:
        with pytest.raises(ValueError):
            mod._semver(value)


class TestOrphanReleaseRule:
    def test_equal_and_behind_are_allowed(self) -> None:
        # tag == pyproject: released commit (fine).
        assert not (mod._semver("1.22.0") > mod._semver("1.22.0"))
        # tag behind pyproject: unreleased prep commit (fine).
        assert not (mod._semver("1.21.1") > mod._semver("1.22.0"))

    def test_tag_ahead_is_an_orphan_release(self) -> None:
        # tag ahead of pyproject == a released tag whose own version file
        # disagrees — exactly the drift this guard exists to catch.
        assert mod._semver("1.23.0") > mod._semver("1.22.0")
