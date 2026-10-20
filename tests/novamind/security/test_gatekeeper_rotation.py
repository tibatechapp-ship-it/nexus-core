"""Security log rotation — the log must never grow without bound.

A phone left running for weeks would otherwise fill its storage with
`memory/security_log.jsonl`. These tests prove the rotation chain is
correct and that rotation can never break logging itself.
"""
import json
from pathlib import Path

import pytest

from novamind.core.security_gatekeeper import (
    DEFAULT_LOG_BACKUPS,
    DEFAULT_LOG_MAX_BYTES,
    SecurityGatekeeper,
    SecurityVerdict,
)


def _verdict() -> SecurityVerdict:
    return SecurityVerdict(
        decision="allow", reason="ok", threat_score=0, threat_level="safe",
        category=None, confidence=0.9,
    )


def _gatekeeper(tmp_path: Path, max_bytes: int = 200, backups: int = 2) -> SecurityGatekeeper:
    gk = SecurityGatekeeper(log_path=tmp_path / "security_log.jsonl")
    gk.max_bytes = max_bytes
    gk.backup_count = backups
    return gk


def _log_many(gk: SecurityGatekeeper, count: int, prefix: str = "req") -> None:
    for i in range(count):
        # A long request so one line reliably exceeds a tiny max_bytes.
        gk._log_verdict(f"{prefix}-{i}-" + "x" * 120, _verdict())


def test_defaults_are_bounded():
    # Constants ship sane values.
    assert DEFAULT_LOG_MAX_BYTES == 10 * 1024 * 1024
    assert DEFAULT_LOG_BACKUPS == 5


def test_env_overrides_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_SECURITY_LOG_MAX_BYTES", "1234")
    monkeypatch.setenv("NEXUS_SECURITY_LOG_BACKUPS", "3")
    gk = SecurityGatekeeper(log_path=tmp_path / "log.jsonl")
    assert gk.max_bytes == 1234
    assert gk.backup_count == 3


def test_log_grows_below_threshold(tmp_path):
    gk = _gatekeeper(tmp_path, max_bytes=10_000)
    _log_many(gk, 3)
    assert gk.log_path.exists()
    lines = gk.log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert not (tmp_path / "security_log.jsonl.1").exists()


def test_rotation_moves_old_file_to_backup_one(tmp_path):
    gk = _gatekeeper(tmp_path, max_bytes=200, backups=2)
    _log_many(gk, 4, prefix="first")
    # Each ~200-char line trips rotation, so only the newest fits per file:
    # active = newest, .1 = the one before it.
    backup = (tmp_path / "security_log.jsonl.1").read_text(encoding="utf-8")
    active = gk.log_path.read_text(encoding="utf-8")
    assert "first-3-" in active
    assert "first-2-" in backup
    # The oldest entry has been dropped entirely (bounded log).
    assert "first-0-" not in active and "first-0-" not in backup


def test_backup_chain_is_ordered_and_bounded(tmp_path):
    gk = _gatekeeper(tmp_path, max_bytes=200, backups=2)
    _log_many(gk, 40, prefix="flood")
    assert (tmp_path / "security_log.jsonl.1").exists()
    assert (tmp_path / "security_log.jsonl.2").exists()
    # Nothing beyond backups+1 total files (active + N backups).
    rotated = sorted(p.name for p in tmp_path.glob("security_log.jsonl.*"))
    assert rotated == ["security_log.jsonl.1", "security_log.jsonl.2"]


def test_zero_backups_truncates_instead_of_rotating(tmp_path):
    gk = _gatekeeper(tmp_path, max_bytes=200, backups=0)
    _log_many(gk, 10)
    assert not (tmp_path / "security_log.jsonl.1").exists()
    # Still a live log (rotation replaced it with an empty file, then appended).
    assert gk.log_path.exists()


def test_rotation_never_raises_when_stat_fails(tmp_path, monkeypatch):
    gk = _gatekeeper(tmp_path, max_bytes=1, backups=1)
    real_stat = Path.stat

    def boom(self, *a, **k):
        if self.name == "security_log.jsonl":
            raise OSError("disk gone")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", boom)
    # Must not raise; the entry is simply not written this time.
    gk._log_verdict("x" * 200, _verdict())


def test_every_line_is_valid_json_after_rotation(tmp_path):
    gk = _gatekeeper(tmp_path, max_bytes=300, backups=1)
    _log_many(gk, 12)
    for path in tmp_path.glob("security_log.jsonl*"):
        if path.name.endswith(".1"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            assert "decision" in entry and "request" in entry
