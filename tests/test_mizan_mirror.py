"""س4 regression tests — the local advisory mirror (docs/MIZAN_ROADMAP.md).

Gap closed: no always-on vulnerability intelligence. The honest stdlib
answer is a local sqlite3 mirror with a *declared* freshness SLA. These
tests pin the س4 exit gate: sync → query → stale → resync, all offline;
an honest status (never-synced is an error, not a fake clean); and the
CLI's CI-shaped exit codes (0 fresh / 1 error / 3 stale).
"""
from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.mizan.advisories import Advisory
from src.mizan.mirror import (
    DEFAULT_SLA_HOURS,
    Mirror,
    MirrorError,
    MirrorStatus,
    staleness_deadline,
)

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "mizan" / "mizan_mirror.py"

_NOW = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)


def _adv(pkg: str = "requests", fixed: str = "2.31.0") -> Advisory:
    return Advisory(package=pkg, vulnerable=f"<{fixed}", fixed=fixed,
                    ids=("GHSA-1111-2222-3333", "CVE-2026-0001"),
                    severity="HIGH")


# ── sync / query / freshness (all offline, deterministic) ────────────────────


def test_sync_then_query_roundtrip(tmp_path: Path) -> None:
    with Mirror(tmp_path / "sub" / "m.db") as m:
        n = m.sync([_adv(), _adv(pkg="flask")], source="offline-file", now=_NOW)
        assert n == 2
        rows = m.query()
        assert {r.package for r in rows} == {"requests", "flask"}
        one = m.query("requests")
        assert one[0].fixed == "2.31.0"
        assert one[0].ids == ("GHSA-1111-2222-3333", "CVE-2026-0001")
        st = m.status(now=_NOW)
        assert st.source == "offline-file"
        assert st.count == 2
        assert st.age_hours == 0.0
        assert not st.stale


def test_sync_replaces_atomically(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv(), _adv(pkg="flask")], now=_NOW)
    m.sync([_adv(pkg="urllib3")], now=_NOW)  # replace-all, not append
    assert [a.package for a in m.query()] == ["urllib3"]
    m.close()


def test_empty_sync_is_reported_not_hidden(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv()], now=_NOW)
    m.sync([], now=_NOW)
    assert m.query() == []
    assert m.status(now=_NOW).count == 0
    m.close()


def test_stale_beyond_sla(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv()], now=_NOW)
    later = _NOW + timedelta(hours=DEFAULT_SLA_HOURS + 0.5)
    st = m.status(now=later)
    assert st.stale
    assert st.age_hours > st.sla_hours
    m.close()


def test_never_synced_is_an_error(tmp_path: Path) -> None:
    with Mirror(tmp_path / "m.db") as m:
        with pytest.raises(MirrorError, match="never synced"):
            m.status(now=_NOW)


def test_corrupt_timestamp_is_an_error(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv()], now=_NOW)
    m.conn.execute("UPDATE meta SET value = 'not-a-date' WHERE key = 'synced_at'")
    m.conn.commit()
    with pytest.raises(MirrorError, match="corrupt"):
        m.status(now=_NOW)
    m.close()


def test_unopenable_mirror_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(MirrorError):
        Mirror(tmp_path)  # a directory cannot be a sqlite file


def test_custom_sla(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db", sla_hours=1.0)
    m.sync([_adv()], now=_NOW)
    assert m.status(now=_NOW + timedelta(minutes=90)).stale
    m.close()


def test_fresh_advisories_convenience(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv()], now=_NOW)
    rows, st = m.fresh_advisories(now=_NOW)
    assert len(rows) == 1
    assert not st.stale
    m.close()


def test_staleness_deadline(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv()], now=_NOW)
    st = m.status(now=_NOW)
    assert staleness_deadline(st) == _NOW + timedelta(hours=DEFAULT_SLA_HOURS)
    m.close()


def test_age_text_mentions_state(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([_adv()], now=_NOW)
    text = m.age_text(now=_NOW)
    assert "fresh" in text and "SLA 24h" in text
    m.close()


def test_status_is_mirrorstatus(tmp_path: Path) -> None:
    m = Mirror(tmp_path / "m.db")
    m.sync([], now=_NOW)
    assert isinstance(m.status(now=_NOW), MirrorStatus)
    m.close()


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
    )


def _advfile(tmp_path: Path) -> Path:
    p = tmp_path / "adv.json"
    p.write_text(
        '{"advisories": [{"package": "requests", "vulnerable": "<2.31.0",'
        ' "fixed": "2.31.0", "ids": ["GHSA-1"], "severity": "HIGH"}]}',
        encoding="utf-8",
    )
    return p


def test_cli_sync_query_status_fresh(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    proc = _run_cli("--db", str(db), "sync", "--advisories", str(_advfile(tmp_path)))
    assert proc.returncode == 0, proc.stderr
    assert "synced 1 advisory" in proc.stdout
    proc = _run_cli("--db", str(db), "query", "requests")
    assert proc.returncode == 0
    assert "requests" in proc.stdout and "2.31.0" in proc.stdout
    proc = _run_cli("--db", str(db), "status", "--require-fresh")
    assert proc.returncode == 0


def test_cli_stale_exit_3(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    advfile = tmp_path / "adv.json"
    # a reviewed file whose sync we backdate by patching the stamp directly
    advfile.write_text(
        '{"advisories": [{"package": "requests", "vulnerable": "<1",'
        ' "fixed": "1", "ids": [], "severity": "LOW"}]}', encoding="utf-8",
    )
    assert _run_cli("--db", str(db), "sync", "--advisories", str(advfile)).returncode == 0
    conn = sqlite3.connect(str(db))
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    conn.execute("UPDATE meta SET value = ? WHERE key = 'synced_at'", (old,))
    conn.commit()
    conn.close()
    proc = _run_cli("--db", str(db), "status", "--require-fresh")
    assert proc.returncode == 3
    assert "STALE" in proc.stderr
    proc = _run_cli("--db", str(db), "status")  # without the flag: informational
    assert proc.returncode == 0


def test_cli_errors(tmp_path: Path) -> None:
    proc = _run_cli("--db", str(tmp_path / "never.db"), "status")
    assert proc.returncode == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = _run_cli("--db", str(tmp_path / "m.db"), "sync", "--advisories", str(bad))
    assert proc.returncode == 1


def test_cli_osv_degradation_keeps_mirror(tmp_path: Path) -> None:
    """Network failure must be loud and must NOT empty the mirror."""
    db = tmp_path / "m.db"
    assert _run_cli("--db", str(db), "sync", "--advisories",
                    str(_advfile(tmp_path))).returncode == 0
    # point the library at a dead port and ask for a live sync
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--db", str(db), "sync", "--osv",
         "--packages", "requests"],
        capture_output=True, text=True, timeout=120,
        env={
            **__import__("os").environ,
            "MIZAN_OSV_URL": "http://127.0.0.1:1",
        },
    )
    assert proc.returncode == 1  # honest failure
    # the previous contents survive
    proc = _run_cli("--db", str(db), "query")
    assert "requests" in proc.stdout
