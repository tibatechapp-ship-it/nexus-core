#!/usr/bin/env python3
"""MIZAN GRC CLI (س5) — aggregate reports into a static governance dashboard.

    python scripts/mizan/mizan_grc.py --report a.json --report b.json
        [--controls FILE | --no-controls] --out dashboard.html [--json PATH]

Reads ``mizan.grc/1`` reports from any number of repositories and renders
one self-contained RTL Arabic HTML file (no JS, no server). Control maps
default to the reviewed built-in file and are labeled *proposed coverage*
— the dashboard never claims certification.

Exit codes:  0 ok · 1 usage/data error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.mizan.grc import (
    GrcError,
    aggregate,
    load_controls,
    load_report,
    render_html,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mizan_grc",
        description="MIZAN GRC: static multi-repo governance dashboard",
    )
    p.add_argument("--report", action="append", required=True, metavar="PATH",
                   help="a mizan.grc/1 report (repeatable)")
    ctrl = p.add_mutually_exclusive_group()
    ctrl.add_argument("--controls", metavar="FILE",
                      help="custom control-map JSON (mizan.controls/1)")
    ctrl.add_argument("--no-controls", action="store_true",
                      help="omit the controls section entirely")
    p.add_argument("--out", required=True, metavar="PATH",
                   help="dashboard HTML output path")
    p.add_argument("--json", metavar="PATH",
                   help="also write the aggregated numbers as JSON")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        reports = [load_report(Path(r)) for r in args.report]
        frameworks = None
        if not args.no_controls:
            frameworks = load_controls(
                Path(args.controls) if args.controls else None
            )
    except GrcError as exc:
        print(f"mizan_grc: {exc}", file=sys.stderr)
        return 1

    portfolio = aggregate(reports)
    html = render_html(portfolio, frameworks)
    Path(args.out).write_text(html, encoding="utf-8")

    totals = portfolio.by_severity()
    print(f"mizan_grc: dashboard → {args.out}")
    print(f"mizan_grc: repos={len(portfolio.latest)} "
          f"open={sum(totals.values())} "
          f"(C={totals['CRITICAL']} H={totals['HIGH']} "
          f"M={totals['MEDIUM']} L={totals['LOW']})")
    if args.json:
        payload = {
            "repos": {
                repo: {
                    "generated_at": rep.generated_at,
                    "open": sum(1 for f in rep.findings if f.is_open),
                    "findings_total": len(rep.findings),
                }
                for repo, rep in sorted(portfolio.latest.items())
            },
            "totals": totals,
            "fixes": {"planned": portfolio.fixes()[0],
                      "applied": portfolio.fixes()[1]},
            "trend": [{"date": d, "open": n} for d, n in portfolio.trend()],
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
