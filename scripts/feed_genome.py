#!/usr/bin/env python3
"""Feed the genome: run one real task per agent through POST /api/chat.

Why /api/chat and NOT /api/orchestrator/execute:
  `/api/orchestrator/execute` routes by KEYWORD — it has no `agent_id` field and
  picks whatever agent the classifier chooses. Feeding 20 agents through it would
  pile every task onto one agent. `/api/chat {agent: <id>}` runs THAT agent and
  its task channel records the outcome against that agent's row.

Usage:
  NEXUS_PORT=8000 python3 scripts/feed_genome.py            # all 20 framework agents
  NEXUS_PORT=8000 python3 scripts/feed_genome.py coder tester

Env:
  NEXUS_PORT        gateway port (default 8000)
  NEXUS_AUTH_TOKEN  required for the mutating POST (read from env or the runit
                    service env dir if absent)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PORT = os.environ.get("NEXUS_PORT", "8000")
BASE = f"http://127.0.0.1:{PORT}"

# One representative task per framework agent (ids from AgentManifest).
TASKS: dict[str, str] = {
    "architect": "design a system for user authentication",
    "coder": "write a python function that adds two numbers",
    "tester": "write a unit test for a math add function",
    "reviewer": "review this code for bugs: def add(a, b): return a-b",
    "documentation": "write a docstring for a function that adds two numbers",
    "researcher": "research best practices for python threading",
    "analyst": "analyze this data: [1, 2, 3, 4, 100]",
    "planner": "plan the steps to build a REST API",
    "estimator": "estimate the effort for a simple login page",
    "security_auditor": "find vulnerabilities in: os.system(input())",
    "compliance": "check if logging passwords violates policy",
    "devops": "configure a CI pipeline for pytest",
    "monitor": "watch memory usage for a python app",
    "recovery": "rollback to previous version after a failed deploy",
    "designer": "design a UI for a login page",
    "performance": "optimize this loop: for i in range(1000): x+=i",
    "refactor": "refactor this: def f(x): return x*2+3",
    "debugger": "diagnose: TypeError: unsupported operand type(s) for +: 'int' and 'str'",
    "reporter": "summarize the results of the last 10 test runs",
    "orchestrator": "route this task: write a test for a function",
}


def _resolve_token() -> str:
    token = os.environ.get("NEXUS_AUTH_TOKEN", "")
    if token:
        return token
    guess = os.path.join(
        os.environ.get("PREFIX", "/data/data/com.termux/files/usr"),
        "var", "service", "nexus-core", "env", "NEXUS_AUTH_TOKEN",
    )
    try:
        with open(guess, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _chat(agent: str, message: str, token: str) -> bool:
    """POST /api/chat (SSE); return True if a real answer streamed."""
    body = json.dumps({"agent": agent, "message": message}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Auth-Token": token,
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code}: {exc.read()[:120]!r}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  ERR {type(exc).__name__}: {exc}")
        return False
    # A completed answer emits at least one chunk / done event.
    return '"type": "chunk"' in raw or "[DONE]" in raw


def _tasked_agents() -> dict[str, int]:
    data = _get("/api/training/fitness")
    return {
        a["agent_id"]: a.get("task_observations", 0)
        for a in data.get("agents", [])
    }


def main(argv: list[str]) -> int:
    token = _resolve_token()
    if not token:
        print("ERR: no NEXUS_AUTH_TOKEN (set env or run the service with its env dir)")
        return 2

    targets = argv or sorted(TASKS)
    before = _tasked_agents()
    print(f"BASE={BASE}  agents={len(targets)}")
    print(f"before: {sum(1 for v in before.values() if v)} agents with tasks\n")

    ok = 0
    for agent in targets:
        task = TASKS.get(agent, "respond with a short confirmation")
        print(f"-> {agent:18s} | {task[:44]}", end=" ")
        succeeded = _chat(agent, task, token)
        print("OK" if succeeded else "FAIL")
        ok += int(succeeded)

    after = _tasked_agents()
    fed = [a for a, n in after.items() if n > before.get(a, 0)]
    print(f"\nanswered: {ok}/{len(targets)}")
    print(f"genome rows that moved: {len(fed)}")
    for agent in sorted(fed):
        print(f"  {agent:20s} tasks={after[agent]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
