#!/usr/bin/env python3
"""Run maintenance tasks against the live orchestrator.

Reads the genome, asks ``task_generator`` for the agents that need attention
most, then (with ``--apply``) posts each LOW/MED request to
``POST /api/orchestrator/execute``. Dry-run BY DEFAULT.

Hard rules baked in:
  * never HIGH risk — the generator filters, and this script refuses anyway;
  * never more than ``--max`` tasks (default 10, env ``NEXUS_MAX_TASKS``);
  * the auth token is read from the environment or the runit service env dir,
    never hardcoded.

Usage:
    python3 scripts/generate_tasks.py                     # show the plan
    python3 scripts/generate_tasks.py --apply             # run them
    python3 scripts/generate_tasks.py --apply --max 3     # cap at 3
    python3 scripts/generate_tasks.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.maintenance.task_generator import (  # noqa: E402  (root set above)
    MAX_LIMIT,
    generate_tasks,
)

DEFAULT_BASE = os.environ.get("NEXUS_BASE", "http://127.0.0.1:8000")
DEFAULT_MAX = 10
_TIMEOUT = 120.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _genome_path() -> Path:
    env = os.environ.get("NEXUS_GENOME_PATH")
    if env:
        return Path(env)
    return _repo_root() / "data" / "genome.json"


def _log_path() -> Path:
    env = os.environ.get("NEXUS_GENERATOR_LOG")
    return Path(env) if env else _repo_root() / "data" / "generator.log"


def _append_log(lines: List[str]) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
    except OSError:
        pass


def _load_genome(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _token() -> str:
    token = os.environ.get("NEXUS_AUTH_TOKEN", "").strip()
    if token:
        return token
    # Fall back to the runit service env dir (absolute, as chpst -e requires).
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    candidate = Path(prefix) / "var" / "service" / "nexus-core" / "env" / "NEXUS_AUTH_TOKEN"
    try:
        return candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _max_tasks(argument: Optional[int]) -> int:
    if argument is not None:
        value = argument
    else:
        try:
            value = int(os.environ.get("NEXUS_MAX_TASKS", DEFAULT_MAX))
        except ValueError:
            value = DEFAULT_MAX
    if value < 1:
        return 1
    return min(value, MAX_LIMIT)


def _post(base: str, path: str, payload: Dict[str, Any], token: str) -> Dict[str, Any]:
    """POST JSON; return ``{ok, status, body}`` and never raise."""
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Auth-Token"] = token
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read().decode("utf-8", "replace")}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "status": 0, "body": str(exc)}
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "status": status, "body": raw}
    return {"ok": status == 200, "status": status, "body": body}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate + run maintenance tasks.")
    parser.add_argument("--apply", action="store_true", help="POST the tasks (default: dry-run)")
    parser.add_argument("--max", type=int, default=None, help="max tasks (<= 10)")
    parser.add_argument("--base", default=DEFAULT_BASE, help="gateway base URL")
    parser.add_argument("--genome", default=None, help="genome.json path override")
    args = parser.parse_args(argv)

    genome_path = Path(args.genome) if args.genome else _genome_path()
    genome = _load_genome(genome_path)
    if genome is None:
        print(f"generate_tasks: no usable genome at {genome_path}", file=sys.stderr)
        return 2

    limit = _max_tasks(args.max)
    tasks = generate_tasks(genome, limit=limit)
    if not tasks:
        print("generate_tasks: no maintenance tasks (genome has no agents)")
        return 0

    # Defense in depth: the generator already drops HIGH, refuse here too.
    safe = [task for task in tasks if task.risk != "high"]
    if len(safe) != len(tasks):
        print("generate_tasks: dropped a HIGH-risk candidate", file=sys.stderr)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"generate_tasks: {mode} — {len(safe)} task(s) from {genome_path}")
    log_lines = [f"generator applied={args.apply} base={args.base} tasks={len(safe)}"]
    token = _token() if args.apply else ""

    failures = 0
    for task in safe:
        print(f"  - [{task.risk}] {task.agent_id}: {task.request}")
        log_lines.append(f"  task risk={task.risk} agent={task.agent_id} {task.request}")
        if not args.apply:
            continue
        result = _post(args.base, "/api/orchestrator/execute", {"request": task.request}, token)
        agent_used = ""
        subtasks = 0
        body = result.get("body")
        if isinstance(body, dict):
            plan = body.get("plan")
            if isinstance(plan, dict):
                agent_used = str(plan.get("agent", ""))
            sub_list = body.get("subtasks")
            subtasks = len(sub_list) if isinstance(sub_list, list) else 0
        status = result.get("status")
        ok = bool(result.get("ok"))
        if not ok:
            failures += 1
        print(f"      -> ok={ok} status={status} agent={agent_used} subtasks={subtasks}")
        log_lines.append(
            f"    result ok={ok} status={status} agent={agent_used} subtasks={subtasks}"
        )

    if not args.apply:
        print("pass --apply to POST them")
    _append_log(log_lines)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
