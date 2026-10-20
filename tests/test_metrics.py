"""Tests for ``src/orchestrator/_metrics.py`` (v1.25.0).

Hermetic: every test passes an explicit ``path`` (or sets ``NEXUS_METRICS_PATH``)
to a ``tmp_path`` file, so the real ``data/metrics.json`` is never touched.
The module must never raise — the whole point is that a broken log degrades to
a no-op rather than breaking an execution.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.orchestrator import _metrics


# ── record / load round-trip ────────────────────────────────────────────────

def test_record_appends_and_load_reads_it_back(tmp_path):
    path = tmp_path / "metrics.json"
    entry = _metrics.record(
        request="write a sum function",
        ok=True,
        decomposed=True,
        subtasks=[{"agent": "coder", "ok": True, "risk": "low"}],
        path=path,
    )
    assert entry is not None
    assert entry["schema"] == _metrics.SCHEMA_VERSION
    assert entry["decomposed"] is True
    assert entry["n_subtasks"] == 1
    assert entry["agents"] == ["coder"]

    rows = _metrics.load(path)
    assert len(rows) == 1
    assert rows[0]["request"] == "write a sum function"


def test_record_defaults_jury_and_derives_risk_from_subtasks(tmp_path):
    path = tmp_path / "metrics.json"
    entry = _metrics.record(
        request="delete the store",
        ok=False,
        decomposed=True,
        subtasks=[
            {"agent": "analyst", "ok": True, "risk": "low"},
            {"agent": "coder", "ok": False, "risk": "high"},
        ],
        path=path,
    )
    assert entry is not None
    # highest subtask risk wins when the caller does not pass one
    assert entry["risk"] == "high"
    assert entry["failed_agents"] == ["coder"]
    assert entry["jury_fired"] is False


def test_record_honours_an_explicit_risk(tmp_path):
    path = tmp_path / "metrics.json"
    entry = _metrics.record(
        request="r", ok=True, decomposed=False, subtasks=[], risk="medium",
        path=path,
    )
    assert entry is not None
    assert entry["risk"] == "medium"


def test_record_truncates_a_long_request(tmp_path):
    path = tmp_path / "metrics.json"
    entry = _metrics.record(
        request="x" * 500, ok=True, decomposed=False, subtasks=[], path=path)
    assert entry is not None
    assert len(entry["request"]) == 200


def test_records_are_bounded_to_max_records(tmp_path, monkeypatch):
    monkeypatch.setattr(_metrics, "MAX_RECORDS", 3)
    path = tmp_path / "metrics.json"
    for i in range(5):
        _metrics.record(request=f"r{i}", ok=True, decomposed=False,
                        subtasks=[], path=path)
    rows = _metrics.load(path)
    assert len(rows) == 3
    # the most RECENT entries are kept
    assert [r["request"] for r in rows] == ["r2", "r3", "r4"]


# ── tolerance: a broken log never raises ────────────────────────────────────

def test_missing_file_loads_as_empty(tmp_path):
    assert _metrics.load(tmp_path / "nope.json") == []


def test_corrupt_file_loads_as_empty(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert _metrics.load(path) == []
    # ...and a record on top of it recovers cleanly
    entry = _metrics.record(request="r", ok=True, decomposed=False,
                            subtasks=[], path=path)
    assert entry is not None
    assert len(_metrics.load(path)) == 1


def test_wrong_shape_file_loads_as_empty(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    assert _metrics.load(path) == []


def test_non_dict_rows_are_filtered_out(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps([{"ok": True}, "junk", 5]), encoding="utf-8")
    assert len(_metrics.load(path)) == 1


def test_unwritable_target_returns_entry_but_does_not_raise(tmp_path):
    # a directory can never be written as a file → best-effort no-op
    entry = _metrics.record(request="r", ok=True, decomposed=False,
                            subtasks=[], path=tmp_path)
    assert entry is not None  # the entry is still returned


# ── path resolution ─────────────────────────────────────────────────────────

def test_default_path_honours_the_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom.json"
    monkeypatch.setenv("NEXUS_METRICS_PATH", str(target))
    assert _metrics.default_metrics_path() == target


def test_default_path_falls_back_inside_the_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_METRICS_PATH", raising=False)
    resolved = _metrics.default_metrics_path()
    assert resolved.name == "metrics.json"
    # the repo root is the checkout this file lives in
    assert Path(_metrics._repo_root()).is_dir()


def test_suite_isolates_metrics_writes_from_the_repo():
    """The suite must never append to the repo's real ``data/metrics.json``.

    ``NEXUS_METRICS_PATH`` is pinned to a private temp file in ``conftest.py``
    at import time, so a test that records (directly or via
    ``/api/orchestrator/execute``) cannot pollute the checkout.
    """
    resolved = _metrics.default_metrics_path()
    repo_data = Path(_metrics._repo_root()) / "data"
    assert repo_data not in resolved.parents, (
        f"default metrics path {resolved} still lives under {repo_data}; "
        "NEXUS_METRICS_PATH must be set to a temp file in conftest.py"
    )

