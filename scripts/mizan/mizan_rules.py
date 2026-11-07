#!/usr/bin/env python3
"""MIZAN rules CLI (س6) — the custom-rules DSL over ``ast``.

    python scripts/mizan/mizan_rules.py check [--rules FILE] [--no-builtin]
           [--json PATH] PATH [PATH ...]
    python scripts/mizan/mizan_rules.py validate FILE

``check`` runs built-in rules (the reviewed ``data/builtin_rules.json``)
plus any custom file over the given paths; ``validate`` load-checks a
rules file without scanning (schema, whitelist, severity, flat regex).

Exit codes:  0 clean · 1 usage/data error · 2 findings reported.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.mizan.rules import (
    RulesError,
    builtin_rules,
    check_path,
    load_rules,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mizan_rules",
        description="MIZAN rules: custom JSON rules over ast",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="scan paths with rules")
    chk.add_argument("paths", nargs="+", metavar="PATH",
                     help="files or directories to scan")
    chk.add_argument("--rules", action="append", default=[], metavar="FILE",
                     help="custom rules file (repeatable)")
    chk.add_argument("--no-builtin", action="store_true",
                     help="skip the shipped built-in rules")
    chk.add_argument("--json", metavar="PATH",
                     help="also write findings as JSON here")
    val = sub.add_parser("validate", help="load-check a rules file")
    val.add_argument("file", metavar="FILE")
    return p.parse_args(argv)


def _collect_rules(args: argparse.Namespace) -> list:
    rules: list = [] if args.no_builtin else builtin_rules()
    for path in args.rules:
        rules.extend(load_rules(Path(path)))
    return rules


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        rules = _collect_rules(args)
    except RulesError as exc:
        print(f"mizan_rules: {exc}", file=sys.stderr)
        return 1
    findings = []
    scanned = 0
    unparsed = 0
    for raw in args.paths:
        root = Path(raw)
        if not root.exists():
            print(f"mizan_rules: no such path: {root}", file=sys.stderr)
            return 1
        f, s, u = check_path(root, rules)
        findings.extend(f)
        scanned += s
        unparsed += u
    print(f"mizan_rules: {len(rules)} rule(s) over {scanned} file(s) "
          f"({unparsed} unparseable)")
    sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    for f in sorted(findings, key=lambda x: (
            sev_rank.get(x.severity, 4), x.path, x.line)):
        hint = f" — fix-hint: {f.fix_hint}" if f.fix_hint else ""
        print(f"  [{f.severity}] {f.rule_id} {f.path}:{f.line} "
              f"{f.message}{hint}")
    if not findings:
        print("mizan_rules: clean")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "rules": len(rules),
            "findings": [
                {"rule_id": f.rule_id, "severity": f.severity,
                 "path": f.path, "line": f.line, "message": f.message,
                 "fix_hint": f.fix_hint, "snippet": f.snippet}
                for f in findings
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 2 if findings else 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        rules = load_rules(Path(args.file))
    except RulesError as exc:
        print(f"mizan_rules: {exc}", file=sys.stderr)
        return 1
    print(f"mizan_rules: {args.file} valid — {len(rules)} rule(s)")
    for r in rules:
        print(f"  {r.id:<16} {r.severity:<9} node={r.node} "
              f"pattern={r.pattern or '(any)'} regex={'yes' if r.regex else 'no'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.cmd == "check":
            return _cmd_check(args)
        return _cmd_validate(args)
    except RulesError as exc:
        print(f"mizan_rules: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
