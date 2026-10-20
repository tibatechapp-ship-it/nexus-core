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


class TestReleaseTagSelection:
    """A non-release tag at HEAD must never be read as the released version.

    Regression: the guard used ``git describe --tags --exact-match``, which
    returns an ARBITRARY tag when several point at the same commit. A
    ``backup/<branch>-<stamp>`` maintenance tag sitting at HEAD (created by the
    release flow) could be returned instead of ``vX.Y.Z``, so the orphan-release
    rule read the wrong string and failed silently. The fix lists every tag at
    HEAD and picks the semver ``v``-tag deterministically.
    """

    @pytest.mark.parametrize(
        "tag,expected",
        [
            ("v1.27.0", "1.27.0"),
            ("v1.20.2", "1.20.2"),
            ("v1.2.3+suffix", "1.2.3+suffix"),
        ],
    )
    def test_release_tags_are_accepted(self, tag: str, expected: str) -> None:
        assert mod._release_version(tag) == expected

    @pytest.mark.parametrize(
        "tag",
        [
            "backup/main-20261020-122531",
            "backup/novamind-factory-20261019",
            "1.27.0",  # no leading v -> not a release tag
            "v1.2",  # not semver
            "vlive",  # not semver
            "",
        ],
    )
    def test_non_release_tags_are_ignored(self, tag: str) -> None:
        assert mod._release_version(tag) is None

    def test_backup_tag_alongside_release_picks_the_release(self) -> None:
        # Exactly the observed bug: two tags at HEAD, describe returned the
        # backup one. Selection must return the version.
        tags = ["backup/main-20261020-122531", "v1.27.0"]
        picked = [
            v for v in (mod._release_version(t) for t in tags) if v
        ]
        assert picked == ["1.27.0"]
        assert max(picked, key=mod._semver) == "1.27.0"

    def test_highest_release_wins_when_several_point_at_head(self) -> None:
        versions = ["v1.26.0", "v1.27.0", "v1.25.0"]
        picked = [v for v in (mod._release_version(t) for t in versions) if v]
        assert max(picked, key=mod._semver) == "1.27.0"

    def test_only_backup_tags_at_head_means_no_release(self) -> None:
        tags = ["backup/main-20261020-122531", "backup/x-20261001"]
        picked = [v for v in (mod._release_version(t) for t in tags) if v]
        assert picked == []


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
