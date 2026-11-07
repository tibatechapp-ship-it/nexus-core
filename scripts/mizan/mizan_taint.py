#!/usr/bin/env python3
"""MIZAN taint CLI (س3) — cross-file source→sink flows, bounded & honest.

    python scripts/mizan/mizan_taint.py [ROOT] [--json PATH]

Prints every attacker-controlled flow that reaches a dangerous sink, with
the chain (source → intermediate calls → sink). The analysis is bounded
(step budget, chain cap); truncation is reported loudly instead of being
passed off as a complete scan.

Exit codes:  0 clean · 1 usage error · 2 findings reported.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.mizan.taint import scan_tree


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mizan_taint",
        description="MIZAN taint: cross-file source→sink analysis",
    )
    p.add_argument("root", nargs="?", default=".",
                   help="project root to scan (default: current directory)")
    p.add_argument("--json", metavar="PATH",
                   help="also write the findings as JSON here")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"mizan_taint: not a directory: {root}", file=sys.stderr)
        return 1

    report = scan_tree(root)
    status = (
        f"mizan_taint: {report.files_scanned} file(s), "
        f"{report.functions} function(s) summarized, "
        f"{report.unparsed} unparseable"
    )
    if report.truncated:
        status += " — TRUNCATED at the step budget (results are partial)"
    print(status)

    for f in report.findings:
        print(f"\n[{f.sink}] {f.file}:{f.line}")
        for i, step in enumerate(f.chain, 1):
            print(f"  {i:>2}. {step}")
    if not report.findings:
        print("mizan_taint: no source→sink flows within the declared scope")

    if args.json:
        payload = {
            "files_scanned": report.files_scanned,
            "unparsed": report.unparsed,
            "functions": report.functions,
            "truncated": report.truncated,
            "findings": [
                {
                    "file": f.file, "line": f.line, "sink": f.sink,
                    "chain": list(f.chain),
                }
                for f in report.findings
            ],
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return 2 if report.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
