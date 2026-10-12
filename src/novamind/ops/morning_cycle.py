#!/usr/bin/env python3
"""HiveLoop Morning Cycle — دورة التشغيل الذاتي"""

from __future__ import annotations
import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hive.orchestration.orchestrator import Orchestrator, Stage
from hive.runtime.base_agent import Task
from hive.memory.task_memory import TaskMemory

logger = logging.getLogger("hive.ops.morning_cycle")

DEFAULT_STAGES = [
    Stage("scout",    ["analyzer", "complexity", "architecture"], mode="parallel"),
    Stage("quality",  ["code_review", "duplication", "deadcode", "naming"], mode="parallel"),
    Stage("security", ["security", "secrets", "injection", "xss"], mode="parallel"),
    Stage("data",     ["dependency", "orm", "sql"], mode="parallel"),
    Stage("docs",     ["documentation", "api_design"], mode="parallel"),
]


class MorningCycle:
    """دورة صباحية كاملة."""

    def __init__(self, objective: str = None, stages: list = None):
        self.objective = objective or "Morning health check"
        self.stages = stages or DEFAULT_STAGES
        self.orch = Orchestrator()
        self.memory = TaskMemory()
        self.started_at = None
        self.finished_at = None
        self.result = None

    async def run(self):
        self.started_at = datetime.now(timezone.utc)
        t0 = time.time()

        print("=" * 60)
        print(f"Morning Cycle - {self.started_at.isoformat()}")
        print("=" * 60)
        print(f"Objective: {self.objective}")
        print(f"Stages:    {len(self.stages)}")
        total_agents = sum(len(s.agents) for s in self.stages)
        print(f"Agents:    {total_agents}")
        print()

        task = Task(objective=self.objective)
        self.result = await self.orch.run_workflow(task, self.stages)

        self.finished_at = datetime.now(timezone.utc)
        elapsed = round(time.time() - t0, 2)

        for stage in self.result.stages:
            print(f"Stage: {stage['name']} ({stage['mode']})")
            for r in stage["results"]:
                status = "OK" if r["status"] == "success" else "FAIL"
                print(f"   [{status}] {r['agent']:20s} {r['duration']}s")
            print()

        summary = self.memory.summary()
        print("=" * 60)
        print("Summary")
        print(f"   Status:          {self.result.status}")
        print(f"   Duration:        {elapsed}s")
        print(f"   Total tasks:     {summary['total_tasks']}")
        print(f"   Success rate:    {summary['success_rate']}")
        print(f"   Agents seen:     {summary['agents_seen']}")
        print("=" * 60)

        return self.result


def write_report(result, path: Path):
    lines = []
    lines.append("# HiveLoop Morning Cycle Report")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**Status**: {result.status}")
    lines.append(f"**Duration**: {result.duration_seconds}s")
    lines.append("")
    lines.append("## Stages")
    lines.append("")
    for stage in result.stages:
        lines.append(f"### {stage['name']} ({stage['mode']})")
        lines.append("")
        lines.append("| Agent | Status | Duration |")
        lines.append("|---|---|---|")
        for r in stage["results"]:
            lines.append(f"| {r['agent']} | {r['status']} | {r['duration']}s |")
        lines.append("")
    path.write_text(chr(10).join(lines), encoding="utf-8")
    return path


async def main():
    parser = argparse.ArgumentParser(prog="morning-cycle")
    parser.add_argument("objective", nargs="?", default=None)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    cycle = MorningCycle(objective=args.objective)
    result = await cycle.run()

    if args.report:
        reports_dir = ROOT / "hive" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = reports_dir / f"morning_{ts}.md"
        write_report(result, report_path)
        print(f"Report: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
