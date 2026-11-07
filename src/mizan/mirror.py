"""Local advisory mirror over ``sqlite3`` (س4) — freshness with an SLA.

The competitive review (MIZAN_ROADMAP.md س4) named the gap: no always-on
vulnerability intelligence. The honest answer for a stdlib-only repo is
*not* a proprietary database — it is a **local mirror** of public sources
(the س1 advisory model) with a declared freshness SLA and a deterministic
offline mode:

* ``sync`` replaces the mirror's contents atomically and stamps the time.
* ``query`` never touches the network — CI reads a stable local copy.
* ``status`` reports the age; ``stale`` compares it to ``SLA_HOURS``
  (24h from public sources by default — declared, not promised).
* An empty/never-synced mirror is an explicit error, not a silent clean.

No zero-days, no proprietary research — the mirror is exactly as fresh as
its last sync, and the status output says so.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .advisories import Advisory

__all__ = ["DEFAULT_SLA_HOURS", "Mirror", "MirrorError", "MirrorStatus"]

#: Declared freshness SLA (hours) — matches MIZAN_ROADMAP.md س4.
DEFAULT_SLA_HOURS = 24.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS advisories (
    package  TEXT NOT NULL,
    vulnerable TEXT NOT NULL DEFAULT '',
    fixed    TEXT NOT NULL DEFAULT '',
    ids      TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'UNKNOWN'
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class MirrorError(RuntimeError):
    """The mirror is unreadable, malformed, or was never synced."""


@dataclass(frozen=True)
class MirrorStatus:
    """One snapshot of the mirror's freshness."""

    synced_at: str
    source: str
    count: int
    age_hours: float
    sla_hours: float

    @property
    def stale(self) -> bool:
        return self.age_hours > self.sla_hours


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Mirror:
    """A single-file advisory mirror (``sqlite3``, stdlib only)."""

    def __init__(self, path: Path, sla_hours: float = DEFAULT_SLA_HOURS) -> None:
        self.path = Path(path)
        self.sla_hours = sla_hours
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.path))
            self.conn.executescript(_SCHEMA)
            self.conn.commit()
        except sqlite3.Error as exc:
            raise MirrorError(f"cannot open mirror {self.path}: {exc}") from exc

    # -- write path --------------------------------------------------------
    def sync(
        self,
        advisories: list[Advisory],
        source: str = "manual",
        now: datetime | None = None,
    ) -> int:
        """Replace the mirror contents atomically and stamp the sync time.

        Returns the number of advisories stored. Re-running sync with an
        empty list is allowed and *reported* (an emptied mirror is a fact
        the caller must see, not something to hide behind the old data).
        """
        stamp = (now or _utcnow()).isoformat()
        try:
            with self.conn:
                self.conn.execute("DELETE FROM advisories")
                self.conn.executemany(
                    "INSERT INTO advisories "
                    "(package, vulnerable, fixed, ids, severity) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (a.package, a.vulnerable, a.fixed,
                         ",".join(a.ids), a.severity)
                        for a in advisories
                    ],
                )
                self.conn.executemany(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    [
                        ("synced_at", stamp),
                        ("source", source),
                        ("count", str(len(advisories))),
                    ],
                )
        except sqlite3.Error as exc:
            raise MirrorError(f"sync failed: {exc}") from exc
        return len(advisories)

    # -- read path ----------------------------------------------------------
    def query(self, package: str | None = None) -> list[Advisory]:
        """Read advisories back (optionally for one package name)."""
        try:
            if package is None:
                cur = self.conn.execute(
                    "SELECT package, vulnerable, fixed, ids, severity "
                    "FROM advisories ORDER BY package, fixed"
                )
            else:
                cur = self.conn.execute(
                    "SELECT package, vulnerable, fixed, ids, severity "
                    "FROM advisories WHERE package = ? ORDER BY fixed",
                    (package,),
                )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise MirrorError(f"query failed: {exc}") from exc
        return [
            Advisory(
                package=r[0], vulnerable=r[1], fixed=r[2],
                ids=tuple(i for i in r[3].split(",") if i), severity=r[4],
            )
            for r in rows
        ]

    def status(self, now: datetime | None = None) -> MirrorStatus:
        """Freshness snapshot; raises when the mirror was never synced."""
        try:
            cur = self.conn.execute(
                "SELECT key, value FROM meta WHERE key IN "
                "('synced_at', 'source', 'count')"
            )
            meta = dict(cur.fetchall())
        except sqlite3.Error as exc:
            raise MirrorError(f"status failed: {exc}") from exc
        if "synced_at" not in meta:
            raise MirrorError(
                "mirror was never synced — run 'sync' first; "
                "refusing to report a freshness we do not have"
            )
        try:
            synced = datetime.fromisoformat(meta["synced_at"])
            if synced.tzinfo is None:
                synced = synced.replace(tzinfo=UTC)
        except ValueError as exc:
            raise MirrorError(
                f"corrupt sync timestamp {meta['synced_at']!r}: {exc}"
            ) from exc
        ref = now or _utcnow()
        age = (ref - synced).total_seconds() / 3600.0
        return MirrorStatus(
            synced_at=meta["synced_at"],
            source=meta.get("source", "unknown"),
            count=int(meta.get("count", "0")),
            age_hours=age,
            sla_hours=self.sla_hours,
        )

    def fresh_advisories(
        self, now: datetime | None = None,
    ) -> tuple[list[Advisory], MirrorStatus]:
        """Query + status in one call — the CI-shaped convenience."""
        st = self.status(now)
        return self.query(), st

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Mirror":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def age_text(self, now: datetime | None = None) -> str:
        """Human one-liner used by the CLI/status output."""
        st = self.status(now)
        state = "STALE" if st.stale else "fresh"
        return (f"{st.count} advisories | synced {st.synced_at} "
                f"({st.age_hours:.1f}h ago) | SLA {st.sla_hours:.0f}h → {state}")


def staleness_deadline(st: MirrorStatus) -> datetime:
    """The instant this mirror crosses its SLA (useful in tests/CI logs)."""
    synced = datetime.fromisoformat(st.synced_at)
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=UTC)
    return synced + timedelta(hours=st.sla_hours)
