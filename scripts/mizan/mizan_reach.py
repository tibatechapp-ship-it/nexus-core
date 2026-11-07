#!/usr/bin/env python3
"""MIZAN reachability CLI (س2) — tri-state verdict per dependency.

    python scripts/mizan/mizan_reach.py [ROOT] (--manifest FILE | --packages a,b)
                                        [--json PATH]

Answers "does the code actually touch this dependency?" with the declared
boundaries of src/mizan/reachability.py: direct imports only, conservative
upward bias (dynamic import ⇒ reachable), and the pip-name vs import-name
approximation printed when a package is absent.

Exit codes:  0 ok · 1 usage/data error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.mizan.manifest import parse_requirements
from src.mizan.reachability import ABSENT, assess_tree

_LIMIT_NOTE = (
    "حدود معلنة: الاستيراد المباشر فقط — الاستخدام الانتقالي (تبعية تابعة، "
    "entry-point، سلسلة ديناميكية) قد يبقى غير مرئي؛ «absent» ليست «غير مستخدمة إطلاقاً»."
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mizan_reach",
        description="MIZAN reachability: import-level tri-state verdicts",
    )
    p.add_argument("root", nargs="?", default=".",
                   help="tree root to scan (default: current directory)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", metavar="FILE",
                     help="assess every package in a requirements manifest")
    src.add_argument("--packages", metavar="a,b,c",
                     help="assess these pip package names directly")
    p.add_argument("--json", metavar="PATH",
                   help="also write the verdicts as JSON here")
    return p.parse_args(argv)


def _package_names(args: argparse.Namespace) -> list[str]:
    if args.packages:
        return [p for p in (s.strip() for s in args.packages.split(",")) if p]
    text = Path(args.manifest).read_text(encoding="utf-8")
    return sorted({
        ln.name for ln in parse_requirements(text)
        if ln.is_requirement and ln.name and not ln.direct_url
    })


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"mizan_reach: not a directory: {root}", file=sys.stderr)
        return 1
    try:
        names = _package_names(args)
    except OSError as exc:
        print(f"mizan_reach: {exc}", file=sys.stderr)
        return 1
    if not names:
        print("mizan_reach: no packages to assess")
        return 0

    assessment = assess_tree(root, names)
    print(f"mizan_reach: {assessment.files_scanned} file(s) scanned, "
          f"{assessment.unparsed} unparseable (counted, not hidden)")
    print(f"{'package':<28} {'verdict':<13} files  call-files")
    for name in sorted(assessment.facts):
        facts = assessment.facts[name]
        print(f"{name:<28} {facts.verdict:<13} "
              f"{len(facts.files_importing):<6} {len(facts.call_files)}")
    absent = [n for n, f in assessment.facts.items() if f.verdict == ABSENT]
    if absent:
        print(f"\nabsent (no direct import): {', '.join(sorted(absent))}")
        print(_LIMIT_NOTE)
    if args.json:
        payload = {
            "root": str(root),
            "files_scanned": assessment.files_scanned,
            "unparsed": assessment.unparsed,
            "packages": {
                n: {
                    "verdict": f.verdict,
                    "files_importing": list(f.files_importing),
                    "call_files": list(f.call_files),
                    "dynamic_import": f.dynamic_import,
                }
                for n, f in assessment.facts.items()
            },
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
