import json
from pathlib import Path

import pytest

from src.llm import request_log


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "request_log.jsonl"
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(log))
    monkeypatch.delenv("NEXUS_REQUEST_LOG_MAX_BYTES", raising=False)
    return log


def _read(path: Path) -> list:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_record_appends(isolated_log: Path) -> None:
    request_log.record(priority="MED", agent_id="a1", outcome="success")
    request_log.record(
        priority="HIGH", agent_id="a2", outcome="failed", reason="timeout"
    )
    rows = _read(isolated_log)
    assert len(rows) == 2
    assert rows[0]["priority"] == "MED"
    assert rows[0]["outcome"] == "success"
    assert "reason" not in rows[0]
    assert rows[1]["priority"] == "HIGH"
    assert rows[1]["reason"] == "timeout"
    assert rows[0]["schema"] == request_log.SCHEMA_VERSION


def test_record_normalises(isolated_log: Path) -> None:
    request_log.record(priority="medium", agent_id="a", outcome="success")
    request_log.record(priority="low", agent_id="a", outcome="success")
    request_log.record(priority="HIGH", agent_id="a", outcome="success")
    rows = _read(isolated_log)
    assert [r["priority"] for r in rows] == ["MED", "LOW", "HIGH"]


def test_record_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bogus = tmp_path / "bogus"
    bogus.mkdir()
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(bogus))
    request_log.record(priority="MED", agent_id="a", outcome="success")


def test_aggregate_empty(isolated_log: Path) -> None:
    out = request_log.aggregate(window_days=7)
    assert out["total_requests"] == 0
    assert out["by_priority"] == {"HIGH": 0, "MED": 0, "LOW": 0}
    assert out["failure_pct"] == 0.0
    assert out["high_pct"] == 0.0
    assert out["sample_sufficient"] is False
    assert "T" in out["sampled_at"]


def test_aggregate_counts(isolated_log: Path) -> None:
    for prio in ("HIGH", "HIGH", "MED", "MED", "MED", "LOW"):
        request_log.record(priority=prio, agent_id="a", outcome="success")
    request_log.record(priority="HIGH", agent_id="a", outcome="failed")
    request_log.record(priority="MED", agent_id="a", outcome="failed", reason="x")
    out = request_log.aggregate(window_days=7)
    assert out["total_requests"] == 8
    assert out["by_priority"] == {"HIGH": 3, "MED": 4, "LOW": 1}
    assert out["failure_pct"] == pytest.approx(25.0)
    assert out["high_pct"] == pytest.approx(37.5)
    assert out["sample_sufficient"] is False


def test_aggregate_window(isolated_log: Path) -> None:
    request_log.record(priority="MED", agent_id="a", outcome="success")
    old = {
        "schema": 1,
        "ts": "2020-01-01T00:00:00+00:00",
        "priority": "HIGH",
        "agent_id": "a",
        "outcome": "failed",
    }
    with isolated_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(old) + "\n")
    assert request_log.aggregate(window_days=7)["total_requests"] == 1
    assert request_log.aggregate(window_days=3650)["total_requests"] == 2


def test_rotation(isolated_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_REQUEST_LOG_MAX_BYTES", "200")
    for i in range(5):
        request_log.record(priority="MED", agent_id="a" + str(i), outcome="success")
    parent = isolated_log.parent
    backups = sorted(
        p.name for p in parent.iterdir() if p.name.startswith(isolated_log.name + ".")
    )
    assert len(backups) >= 1
    for name in backups:
        suffix = name.rsplit(".", 1)[-1]
        assert suffix.isdigit()
        assert 1 <= int(suffix) <= request_log.BACKUPS


# ── Coverage gap fills: env overrides, rotation, malformed inputs ─────────────

def test_max_bytes_env_override(isolated_log, monkeypatch):
    """_max_bytes() honours NEXUS_REQUEST_LOG_MAX_BYTES."""
    monkeypatch.setenv("NEXUS_REQUEST_LOG_MAX_BYTES", "512")
    from src.llm.request_log import _max_bytes
    assert _max_bytes() == 512


def test_max_bytes_env_invalid_falls_back(monkeypatch):
    """Invalid env value → MAX_BYTES fallback."""
    monkeypatch.setenv("NEXUS_REQUEST_LOG_MAX_BYTES", "not-an-int")
    from src.llm.request_log import _max_bytes, MAX_BYTES
    assert _max_bytes() == MAX_BYTES


def test_max_bytes_env_zero_clamps_to_one(monkeypatch):
    """Zero/negative is clamped to 1, never raises."""
    monkeypatch.setenv("NEXUS_REQUEST_LOG_MAX_BYTES", "0")
    from src.llm.request_log import _max_bytes
    assert _max_bytes() == 1


def test_rotate_missing_file_is_noop(tmp_path):
    """_rotate() on a non-existent path does nothing."""
    from src.llm.request_log import _rotate
    _rotate(tmp_path / "nope.jsonl")  # must not raise


def test_rotate_moves_existing_files(tmp_path):
    """_rotate() shifts .jsonl → .1 → .2 …"""
    from src.llm.request_log import _rotate
    log = tmp_path / "request_log.jsonl"
    log.write_text("current\n")
    (tmp_path / "request_log.jsonl.1").write_text("one\n")
    (tmp_path / "request_log.jsonl.2").write_text("two\n")

    _rotate(log)

    assert not log.exists()
    assert (tmp_path / "request_log.jsonl.1").read_text() == "current\n"
    assert (tmp_path / "request_log.jsonl.2").read_text() == "one\n"
    assert (tmp_path / "request_log.jsonl.3").read_text() == "two\n"


def test_record_rotates_when_size_exceeded(isolated_log, monkeypatch):
    """record() triggers _rotate when size >= max_bytes."""
    monkeypatch.setenv("NEXUS_REQUEST_LOG_MAX_BYTES", "10")
    from src.llm import request_log
    request_log.record(priority="MED", agent_id="a", outcome="success")
    request_log.record(priority="MED", agent_id="b", outcome="success")

    # After the second write, the first file should have been rotated.
    assert (isolated_log.parent / "request_log.jsonl.1").exists()


def test_record_swallows_unwritable_path(monkeypatch):
    """record() never raises even if the path can't be opened."""
    monkeypatch.setenv("NEXUS_REQUEST_LOG", "/proc/nonexistent/request_log.jsonl")
    from src.llm import request_log
    request_log.record(priority="HIGH", agent_id="a", outcome="failed")


def test_aggregate_handles_empty_and_missing_log(tmp_path, monkeypatch):
    """aggregate() returns a well-formed dict on an empty/missing log."""
    from src.llm import request_log
    monkeypatch.setenv("NEXUS_REQUEST_LOG", str(tmp_path / "missing.jsonl"))
    out = request_log.aggregate()
    assert out["total_requests"] == 0
    assert out["by_priority"] == {"HIGH": 0, "MED": 0, "LOW": 0}
    assert out["failure_pct"] == 0.0
    assert out["high_pct"] == 0.0
    assert out["sample_sufficient"] is False


def test_aggregate_window_days_invalid_falls_back(isolated_log):
    """Non-int or negative window_days → 7-day default (no crash)."""
    from src.llm import request_log
    out = request_log.aggregate(window_days="nope")  # type: ignore[arg-type]
    assert "total_requests" in out


def test_aggregate_ignores_malformed_lines(isolated_log):
    """Blank lines, non-JSON, non-dict rows, bad timestamps are skipped."""
    import json
    from src.llm import request_log

    lines = [
        "",
        "   ",
        "not-json",
        json.dumps(["a", "list"]),       # not a dict
        json.dumps({"ts": "not-a-date"}),# bad ts
        json.dumps({"ts": "2020-01-01T00:00:00"}),  # no tz → UTC fallback, but old → skipped
        json.dumps({"ts": "not-a-date", "priority": "HIGH"}),  # bad ts
    ]
    isolated_log.write_text("\n".join(lines) + "\n")

    out = request_log.aggregate()
    assert out["total_requests"] == 0


def test_aggregate_counts_only_in_window(isolated_log):
    """Rows older than window_days are excluded."""
    import datetime
    import json
    from src.llm import request_log

    now = datetime.datetime.now(datetime.timezone.utc)
    recent = now.isoformat(timespec="seconds")
    old = (now - datetime.timedelta(days=30)).isoformat(timespec="seconds")

    rows = [
        {"schema": 1, "ts": recent, "priority": "HIGH", "agent_id": "a", "outcome": "success"},
        {"schema": 1, "ts": old, "priority": "HIGH", "agent_id": "b", "outcome": "success"},
    ]
    isolated_log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    out = request_log.aggregate(window_days=7)
    assert out["total_requests"] == 1
    assert out["by_priority"]["HIGH"] == 1


def test_aggregate_unknown_priority_is_ignored(isolated_log):
    """Unknown priority is skipped from by_priority but counted in total."""
    import datetime
    import json
    from src.llm import request_log

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rows = [
        {"schema": 1, "ts": now, "priority": "WEIRD", "agent_id": "a", "outcome": "success"},
    ]
    isolated_log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    out = request_log.aggregate()
    assert out["total_requests"] == 1
    assert out["by_priority"] == {"HIGH": 0, "MED": 0, "LOW": 0}


def test_aggregate_failure_counted(isolated_log):
    """Non-success outcome increments failures."""
    import datetime
    import json
    from src.llm import request_log

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rows = [
        {"schema": 1, "ts": now, "priority": "HIGH", "agent_id": "a", "outcome": "failed"},
        {"schema": 1, "ts": now, "priority": "HIGH", "agent_id": "b", "outcome": "success"},
    ]
    isolated_log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    out = request_log.aggregate()
    assert out["failure_pct"] == 50.0
    assert out["high_pct"] == 100.0


# ── Coverage: OSError/exception paths ─────────────────────────────────────────

def test_path_falls_back_to_tmpdir_when_data_unwritable(monkeypatch):
    """_path() falls back to tempdir when data/ can't be created."""
    from unittest.mock import patch
    from src.llm import request_log

    monkeypatch.delenv("NEXUS_REQUEST_LOG", raising=False)

    # Simulate: Path(__file__).resolve().parents[2] / "data" -> mkdir raises
    real_mkdir = Path.mkdir

    def _fail_on_data(self, *a, **kw):
        if str(self).endswith("/data"):
            raise OSError("simulated: read-only")
        return real_mkdir(self, *a, **kw)

    with patch.object(Path, "mkdir", _fail_on_data):
        p = request_log._path()

    import tempfile
    assert str(p).startswith(tempfile.gettempdir())
    assert p.name == "nexus_request_log.jsonl"


def test_rotate_skips_existing_destination(tmp_path):
    """_rotate() unlinks an existing destination before renaming."""
    from src.llm import request_log

    log = tmp_path / "request_log.jsonl"
    log.write_text("current\n")
    (tmp_path / "request_log.jsonl.1").write_text("stale\n")

    request_log._rotate(log)

    # .1 now holds the old current, .2 doesn't exist yet
    assert (tmp_path / "request_log.jsonl.1").read_text() == "current\n"


def test_rotate_swallows_oserror(tmp_path, monkeypatch):
    """_rotate() never raises if rename fails."""
    from unittest.mock import patch
    from src.llm import request_log

    log = tmp_path / "request_log.jsonl"
    log.write_text("current\n")

    def _boom(self, target):
        raise OSError("simulated rename failure")

    with patch.object(Path, "rename", _boom):
        request_log._rotate(log)  # must not raise


def test_record_swallows_stat_error(isolated_log):
    """record() still writes even if path.stat() raises (no rotation triggered)."""
    from unittest.mock import patch
    from src.llm import request_log

    real_stat = Path.stat

    def _boom_stat(self, *a, **kw):
        if str(self).endswith("request_log.jsonl"):
            raise OSError("simulated stat failure")
        return real_stat(self, *a, **kw)

    with patch.object(Path, "stat", _boom_stat):
        request_log.record(priority="MED", agent_id="a", outcome="success")

    rows = _read(isolated_log)
    assert len(rows) == 1


def test_parse_ts_handles_invalid_iso():
    """_parse_ts returns None for unparseable strings."""
    from src.llm import request_log
    assert request_log._parse_ts("not-a-date") is None
    assert request_log._parse_ts(123) is None
    assert request_log._parse_ts(None) is None


def test_aggregate_swallows_read_error(isolated_log, monkeypatch):
    """aggregate() returns a zeroed dict if reading the log raises."""
    from unittest.mock import patch
    from src.llm import request_log

    def _boom_read(self, *a, **kw):
        raise OSError("simulated read failure")

    with patch.object(Path, "read_text", _boom_read):
        out = request_log.aggregate()

    assert out["total_requests"] == 0
    assert out["sample_sufficient"] is False
