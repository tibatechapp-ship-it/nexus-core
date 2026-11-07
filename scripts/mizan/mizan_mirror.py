#!/usr/bin/env python3
"""MIZAN mirror CLI (س4) — local advisory mirror with a freshness SLA.

    python scripts/mizan/mizan_mirror.py --db PATH sync
        (--advisories FILE | --osv [--manifest FILE | --packages a,b])
    python scripts/mizan/mizan_mirror.py --db PATH query [PACKAGE]
    python scripts/mizan/mizan_mirror.py --db PATH status [--require-fresh]

The mirror is exactly as fresh as its last sync — ``status`` prints the
age against the declared 24h SLA, and ``--require-fresh`` turns staleness
into a CI-failing exit so dashboards never read a rotted copy silently.

Exit codes:  0 ok/fresh · 1 usage/data error · 3 stale (with --require-fresh).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.mizan import advisories as _advisories_mod
from src.mizan.advisories import AdvisoryError, fetch_osv, load_offline
from src.mizan.manifest import parse_requirements
from src.mizan.mirror import Mirror, MirrorError

DEFAULT_DB = ".mizan/advisories.db"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mizan_mirror",
        description="MIZAN mirror: local advisory cache with an SLA",
    )
    p.add_argument("--db", default=DEFAULT_DB, help="mirror database path")
    sub = p.add_subparsers(dest="cmd", required=True)
    sync = sub.add_parser("sync", help="replace mirror contents and stamp")
    src = sync.add_mutually_exclusive_group(required=True)
    src.add_argument("--advisories", metavar="FILE",
                     help="offline reviewed advisories JSON")
    src.add_argument("--osv", action="store_true",
                     help="fetch live from OSV.dev")
    sync.add_argument("--manifest", metavar="FILE",
                      help="requirements manifest to derive package names")
    sync.add_argument("--packages", metavar="a,b,c",
                      help="explicit package names")
    q = sub.add_parser("query", help="read advisories back (optionally one)")
    q.add_argument("package", nargs="?", default=None)
    st = sub.add_parser("status", help="freshness snapshot")
    st.add_argument("--require-fresh", action="store_true",
                    help="exit 3 when older than the SLA")
    return p.parse_args(argv)


def _sync_packages(args: argparse.Namespace) -> list[str]:
    if args.packages:
        return [p for p in (s.strip() for s in args.packages.split(",")) if p]
    if args.manifest:
        text = Path(args.manifest).read_text(encoding="utf-8")
        return sorted({
            ln.name for ln in parse_requirements(text)
            if ln.is_requirement and ln.name and not ln.direct_url
        })
    return []


def _load_for_sync(args: argparse.Namespace) -> tuple[list, str]:
    if args.advisories:
        return load_offline(Path(args.advisories)), "offline-file"
    names = _sync_packages(args)
    # declared CI/test hook: point the live source at a stub/dead URL to
    # exercise honest degradation without real network access
    override = os.environ.get("MIZAN_OSV_URL")
    if override:
        _advisories_mod.osv_url = override
    try:
        return fetch_osv(names), "osv.dev"
    except AdvisoryError as exc:
        # honest degradation: the mirror keeps its previous contents and
        # the failure is loud — never an empty "clean-looking" mirror.
        raise MirrorError(f"OSV fetch failed; mirror unchanged ({exc})") from exc


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        with Mirror(Path(args.db)) as mirror:
            if args.cmd == "sync":
                advisories, source = _load_for_sync(args)
                n = mirror.sync(advisories, source=source)
                print(f"mizan_mirror: synced {n} advisory(ies) from {source}")
                print(f"mizan_mirror: {mirror.age_text()}")
                return 0
            if args.cmd == "query":
                rows = mirror.query(args.package)
                for a in rows:
                    ids = ", ".join(a.ids) or "—"
                    print(f"{a.package:<28} {a.severity:<8} "
                          f"vuln={a.vulnerable or '—':<14} fixed={a.fixed or '—':<10} {ids}")
                print(f"mizan_mirror: {len(rows)} row(s) — {mirror.age_text()}")
                return 0
            # status
            st = mirror.status()
            print(f"mizan_mirror: {mirror.age_text()}")
            if args.require_fresh and st.stale:
                print(f"mizan_mirror: STALE beyond the {st.sla_hours:.0f}h SLA",
                      file=sys.stderr)
                return 3
            return 0
    except (MirrorError, AdvisoryError) as exc:
        print(f"mizan_mirror: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
