"""Regression tests for agent-cache key isolation and safe persistence."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

import src.orchestrator.agent_cache as cache


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cache, "_CACHE_DIR", str(tmp_path))
    return tmp_path


def test_cache_key_uses_complete_prompt(tmp_cache: Path) -> None:
    prefix = "x" * 250
    assert cache._key("coder", prefix + "A") != cache._key("coder", prefix + "B")


def test_cache_key_is_path_safe_and_agent_scoped() -> None:
    key = cache._key("../../outside", "prompt")
    assert "/" not in key and "\\" not in key and key not in {".", ".."}
    assert key != cache._key("outside", "prompt")


def test_cache_set_get_roundtrip_and_private_file_mode(tmp_cache: Path) -> None:
    assert cache.get("a", "p") is None
    cache.set("a", "p", {"v": 1})
    assert cache.get("a", "p") == {"v": 1}
    entry = tmp_cache / (cache._key("a", "p") + ".json")
    assert stat.S_IMODE(entry.stat().st_mode) == 0o600


def test_cache_expired_entry_removed(tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache.set("a", "p", "x")
    monkeypatch.setattr(cache, "_TTL", -1)
    assert cache.get("a", "p") is None


def test_cache_corrupt_and_non_object_entries_are_misses(tmp_cache: Path) -> None:
    corrupt = tmp_cache / (cache._key("a", "p") + ".json")
    corrupt.write_text("{not json", encoding="utf-8")
    assert cache.get("a", "p") is None

    invalid = tmp_cache / (cache._key("b", "p") + ".json")
    invalid.write_text('["not", "an", "entry"]', encoding="utf-8")
    assert cache.get("b", "p") is None


def test_cache_invalid_timestamp_is_a_miss(tmp_cache: Path) -> None:
    entry = tmp_cache / (cache._key("a", "p") + ".json")
    entry.write_text('{"ts": "not-a-number", "result": "bad"}', encoding="utf-8")
    assert cache.get("a", "p") is None


def test_cache_replace_failure_cleans_temporary_file(
    tmp_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(source: str, destination: str) -> None:
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(cache.os, "replace", fail_replace)
    cache.set("a", "p", "x")
    assert cache.get("a", "p") is None
    assert list(tmp_cache.iterdir()) == []


def test_cache_does_not_follow_symlink(tmp_cache: Path) -> None:
    outside = tmp_cache.parent / "outside-cache.json"
    outside.write_text('{"ts": 9999999999, "result": "private"}', encoding="utf-8")
    entry = tmp_cache / (cache._key("a", "p") + ".json")
    try:
        entry.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")
    assert cache.get("a", "p") is None


def test_cache_write_failure_is_non_fatal(tmp_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_CACHE_DIR", str(tmp_cache / "missing" / "deeper"))
    cache.set("a", "p", "x")
    assert cache.get("a", "p") is None
