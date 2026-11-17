"""Command-line interface for the NEXUS digital-work proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.digital_work.pipeline import execute_run, run_demo, validate_run


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS real digital-work execution proof")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="create 30 files and run clean/corrupted workflows")
    demo.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="process an existing input directory")
    run.add_argument("input", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--run-id", default="manual")
    validate = commands.add_parser("validate", help="independently validate a previous run")
    validate.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    if args.command == "demo":
        result = run_demo(args.output)
    elif args.command == "run":
        result = execute_run(args.input, args.output, run_id=args.run_id)
    else:
        result = validate_run(args.run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
