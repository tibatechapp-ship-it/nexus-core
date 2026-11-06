#!/usr/bin/env python3
"""MIZAN auto-fix CLI (س1) — plan (default) / apply dependency fixes.

    python scripts/mizan/mizan_fix.py [PATH] [--advisories FILE | --osv]
                                    [--apply] [--diff-file PATH]
                                    [--report-md PATH]

The planner is deterministic (mizan.fixer): no LLM, no guessing — the target
is always the highest declared fixed version pinned exactly. Dry-run is the
default; ``--apply`` rewrites the manifest in place. Exit codes:

    0  clean (no fixes needed), applied successfully, or honestly degraded
    1  usage/data error (missing manifest, unreadable advisories)
    2  fixes available (plan mode only — lets CI detect "actionable")
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.mizan.advisories import Advisory, AdvisoryError, fetch_osv, load_offline
from src.mizan.fixer import PlanResult, apply_plans, plan_fixes, render_diff
from src.mizan.manifest import normalize_name, parse_requirements


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mizan_fix",
        description="MIZAN auto-fix: deterministic dependency remediation",
    )
    p.add_argument("path", nargs="?", default="requirements.txt",
                   help="requirements manifest (default: requirements.txt)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--advisories", metavar="FILE",
                     help="offline reviewed advisories JSON")
    src.add_argument("--osv", action="store_true",
                     help="fetch advisories live from OSV.dev")
    p.add_argument("--apply", action="store_true",
                   help="write the fixed manifest (default: dry-run)")
    p.add_argument("--diff-file", metavar="PATH",
                   help="also write the unified diff here")
    p.add_argument("--report-md", metavar="PATH",
                   help="also write a markdown report here (fix-PR body)")
    return p.parse_args(argv)


def _severity_sort_key(sev: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(sev.upper(), 1)


def _report_md(path: Path, result: PlanResult) -> None:
    lines = [
        "## MIZAN auto-fix — خطة إصلاح حتمية (س1)",
        "",
        "| الحزمة | الحالي | الهدف | الخطورة | الإعلانات |",
        "|---|---|---|---|---|",
    ]
    for p in sorted(result.plans,
                    key=lambda x: -_severity_sort_key(x.severity)):
        ids = ", ".join(p.advisory_ids) or "—"
        lines.append(
            f"| {p.display_name} | `{p.current_spec}` | `{p.target_spec}` "
            f"| {p.severity} | {ids} |"
        )
    if result.skipped:
        lines += ["", "### تخطٍّ معلن", ""]
        for s in result.skipped:
            lines.append(f"- `{s.package}` (سطر {s.line_index + 1}): {s.reason}")
    lines += [
        "",
        "الهدف دائمًا أدنى إصدار مُصلح معلن مُثبّتًا بـ `==` — بلا تخمين.",
        "المراجعة البشرية شرط الدمج (PR بواسطة GITHUB_TOKEN لا يشغّل CI تلقائيًا).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _emit_side_files(
    args: argparse.Namespace, original: str, updated: str, result: PlanResult,
) -> None:
    if args.diff_file:
        Path(args.diff_file).write_text(
            render_diff(original, updated, args.path), encoding="utf-8",
        )
    if args.report_md:
        _report_md(Path(args.report_md), result)


def _print_plans(result: PlanResult) -> None:
    for p in result.plans:
        print(f"  {p.display_name}: {p.current_spec} → {p.target_spec} "
              f"[{p.severity}] {', '.join(p.advisory_ids) or '(no ids)'}")
    for s in result.skipped:
        print(f"  skip {s.package}: {s.reason}", file=sys.stderr)


def _load_advisories(args: argparse.Namespace, req_names: list[str]) -> list[Advisory]:
    if args.advisories:
        return load_offline(Path(args.advisories))
    try:
        return fetch_osv(req_names)
    except AdvisoryError as exc:
        # Honest degradation: unreachable intel source ⇒ no advisories and a
        # loud stderr note; never fabricate a clean or a fix from nothing.
        print(f"MIZAN auto-fix: degraded — {exc}", file=sys.stderr)
        return []


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = Path(args.path)
    try:
        original = manifest.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"MIZAN auto-fix: cannot read {manifest}: {exc}", file=sys.stderr)
        return 1

    reqs = parse_requirements(original)
    names = sorted({ln.name for ln in reqs if ln.is_requirement and ln.name})
    try:
        advisories = _load_advisories(args, names)
    except AdvisoryError as exc:  # malformed offline file — a real error
        print(f"MIZAN auto-fix: {exc}", file=sys.stderr)
        return 1

    result = plan_fixes(reqs, advisories)
    if not result.changed:
        print("MIZAN auto-fix: no actionable fixes")
        _emit_side_files(args, original, original, result)
        return 0

    updated = apply_plans(original, reqs, result.plans)
    _emit_side_files(args, original, updated, result)
    if args.apply:
        manifest.write_text(updated, encoding="utf-8")
        print(f"MIZAN auto-fix: applied {len(result.plans)} fix(es) to {manifest}")
        return 0
    print(f"MIZAN auto-fix: {len(result.plans)} fix(es) available (dry-run):")
    _print_plans(result)
    print(render_diff(original, updated, args.path))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
