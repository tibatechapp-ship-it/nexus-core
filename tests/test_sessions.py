"""Tests for src/sessions/manager.py — persistent work sessions."""

from __future__ import annotations

import json
from pathlib import Path

from src.sessions.manager import Session, SessionManager


def test_session_new_fields() -> None:
    s = Session.new(title="T", agent="coder")
    assert s.id.startswith("ses_")
    assert s.title == "T"
    assert s.agent == "coder"
    assert s.backend == "ollama"
    assert s.messages == []
    assert s.metadata == {}
    assert s.created_at and s.updated_at


def test_add_message_updates_timestamp_and_message() -> None:
    s = Session.new()
    s.add_message("user", "hi", extra_field=1)
    assert s.messages[0]["role"] == "user"
    assert s.messages[0]["content"] == "hi"
    assert s.messages[0]["extra_field"] == 1
    assert "timestamp" in s.messages[0]
    assert s.updated_at


def test_to_from_dict_roundtrip() -> None:
    s = Session.new(title="x")
    s.add_message("assistant", "y")
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_manager_create_save_load(tmp_path: Path) -> None:
    m = SessionManager(base_dir=tmp_path)
    s = m.create(title="hello", agent="analyst")
    assert (tmp_path / f"{s.id}.json").exists()
    loaded = m.load(s.id)
    assert loaded is not None and loaded.title == "hello"


def test_load_missing_and_corrupt(tmp_path: Path) -> None:
    m = SessionManager(base_dir=tmp_path)
    assert m.load("ses_missing") is None
    bad = tmp_path / "ses_bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert m.load("ses_bad") is None


def test_list_sessions_order_limit_and_corrupt_skip(tmp_path: Path) -> None:
    m = SessionManager(base_dir=tmp_path)
    a = m.create(title="first")
    b = m.create(title="second")
    # corrupt file must be skipped, not crash
    (tmp_path / "ses_corrupt.json").write_text("nope", encoding="utf-8")
    sessions = m.list_sessions(limit=50)
    assert {s.id for s in sessions} == {a.id, b.id}
    assert m.list_sessions(limit=1)[0].id in {a.id, b.id}


def test_delete(tmp_path: Path) -> None:
    m = SessionManager(base_dir=tmp_path)
    s = m.create()
    assert m.delete(s.id) is True
    assert m.delete(s.id) is False


def test_latest_empty_and_present(tmp_path: Path) -> None:
    m = SessionManager(base_dir=tmp_path)
    assert m.latest() is None
    m.create(title="only")
    latest = m.latest()
    assert latest is not None and latest.title == "only"


def test_export(tmp_path: Path) -> None:
    m = SessionManager(base_dir=tmp_path)
    s = m.create(title="exp")
    dest = tmp_path / "out.json"
    out = m.export(s.id, dest)
    assert out == dest and dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8"))["title"] == "exp"


def test_export_missing_raises(tmp_path: Path) -> None:
    import pytest

    m = SessionManager(base_dir=tmp_path)
    with pytest.raises(ValueError):
        m.export("ses_missing", tmp_path / "x.json")
