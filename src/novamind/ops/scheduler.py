#!/usr/bin/env python3
"""HiveLoop Scheduler — الجدولة التلقائية"""

from __future__ import annotations
import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hive.ops.morning_cycle import MorningCycle, write_report

logger = logging.getLogger("hive.ops.scheduler")


class Job:
    """مهمة مجدولة."""

    def __init__(self, name: str, interval_seconds: int, func: Callable,
                 run_on_start: bool = False):
        self.name = name
        self.interval_seconds = interval_seconds
        self.func = func
        self.run_on_start = run_on_start
        self.last_run: Optional[float] = None
        self.runs = 0
        self.failures = 0
        self.total_duration = 0.0

    def is_due(self, now: float) -> bool:
        if self.last_run is None:
            return self.run_on_start
        return (now - self.last_run) >= self.interval_seconds

    async def run(self):
        t0 = time.time()
        try:
            logger.info(f"[{self.name}] starting...")
            if asyncio.iscoroutinefunction(self.func):
                await self.func()
            else:
                self.func()
            self.runs += 1
            duration = time.time() - t0
            self.total_duration += duration
            logger.info(f"[{self.name}] done in {duration:.2f}s")
        except Exception as e:
            self.failures += 1
            logger.error(f"[{self.name}] failed: {e}", exc_info=True)
        finally:
            self.last_run = time.time()

    def stats(self) -> Dict:
        return {
            "name": self.name,
            "interval_seconds": self.interval_seconds,
            "runs": self.runs,
            "failures": self.failures,
            "avg_duration": round(self.total_duration / self.runs, 2) if self.runs else 0.0,
            "last_run": datetime.fromtimestamp(self.last_run, timezone.utc).isoformat() if self.last_run else None,
        }


# ============================================================
# JOBS
# ============================================================

async def job_morning_cycle():
    """Morning cycle كامل."""
    cycle = MorningCycle(objective="Scheduled morning health check")
    result = await cycle.run()

    # اكتب تقرير
    reports_dir = ROOT / "hive" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"morning_{ts}.md"
    write_report(result, report_path)
    logger.info(f"Report: {report_path}")


async def job_health_check():
    """فحص سريع."""
    from hive.runtime.pool import AgentPool
    from hive.runtime.base_agent import Task

    pool = AgentPool(max_concurrent=5)
    task = Task(objective="Quick health check")
    result = await pool.run_one("analyzer", task)
    logger.info(f"Health: {result.status} ({result.duration_seconds}s)")


async def job_slo_review():
    """مراجعة SLO."""
    from hive.memory.task_memory import TaskMemory
    mem = TaskMemory()
    summary = mem.summary()
    logger.info(f"SLO: success_rate={summary['success_rate']}, total={summary['total_tasks']}")


async def job_weekly_report():
    """تقرير أسبوعي."""
    from hive.memory.task_memory import TaskMemory
    mem = TaskMemory()
    summary = mem.summary()
    stats = mem.agent_stats()

    reports_dir = ROOT / "hive" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    report_path = reports_dir / f"weekly_{ts}.md"

    lines = []
    lines.append(f"# Weekly Report - {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Total tasks: {summary['total_tasks']}")
    lines.append(f"- Success rate: {summary['success_rate']}")
    lines.append(f"- Agents seen: {summary['agents_seen']}")
    lines.append("")
    lines.append("## Top Agents")
    lines.append("")
    lines.append("| Agent | Runs | Success | Rate |")
    lines.append("|---|---|---|---|")
    for s in stats[:20]:
        total = s["total_runs"] or 1
        rate = s["successes"] / total
        lines.append(f"| {s['agent_id']} | {total} | {s['successes']} | {rate:.2f} |")

    report_path.write_text(chr(10).join(lines), encoding="utf-8")
    logger.info(f"Weekly report: {report_path}")


# ============================================================
# SCHEDULER
# ============================================================

class Scheduler:
    """جدول تشغيل المهام."""

    def __init__(self, tick_seconds: int = 30):
        self.tick_seconds = tick_seconds
        self.jobs: List[Job] = []
        self.running = False

    def add_job(self, job: Job):
        self.jobs.append(job)
        logger.info(f"Registered job: {job.name} (every {job.interval_seconds}s)")

    async def run(self, duration_seconds: Optional[int] = None):
        """شغّل الجدول."""
        self.running = True
        t0 = time.time()

        print("=" * 60)
        print("HiveLoop Scheduler")
        print("=" * 60)
        print(f"Tick: {self.tick_seconds}s")
        print(f"Jobs: {len(self.jobs)}")
        for j in self.jobs:
            print(f"  - {j.name:20s} every {j.interval_seconds}s")
        print()
        print("Press Ctrl+C to stop")
        print("=" * 60)

        try:
            while self.running:
                now = time.time()

                # افحص المهام المستحقة
                for job in self.jobs:
                    if job.is_due(now):
                        await job.run()

                # فحص المدة
                if duration_seconds and (time.time() - t0) >= duration_seconds:
                    print()
                    print(f"Duration reached ({duration_seconds}s). Stopping.")
                    break

                await asyncio.sleep(self.tick_seconds)

        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            self.print_stats()

    def print_stats(self):
        print()
        print("=" * 60)
        print("Scheduler Stats")
        print("=" * 60)
        for job in self.jobs:
            s = job.stats()
            print(f"  {s['name']:20s}: runs={s['runs']}, failures={s['failures']}, avg={s['avg_duration']}s")
        print("=" * 60)

    def stop(self):
        self.running = False


# ============================================================
# MAIN
# ============================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(prog="scheduler")
    parser.add_argument("--duration", type=int, default=0,
                        help="Run for N seconds (0 = forever)")
    parser.add_argument("--tick", type=int, default=30,
                        help="Tick interval in seconds")
    parser.add_argument("--fast", action="store_true",
                        help="Fast test mode (short intervals)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    scheduler = Scheduler(tick_seconds=args.tick)

    if args.fast:
        # وضع الاختبار السريع
        scheduler.add_job(Job("health_check", 5, job_health_check, run_on_start=True))
        scheduler.add_job(Job("slo_review", 10, job_slo_review))
        scheduler.add_job(Job("morning_cycle", 20, job_morning_cycle))
    else:
        # الإنتاج
        scheduler.add_job(Job("morning_cycle", 86400, job_morning_cycle, run_on_start=True))
        scheduler.add_job(Job("health_check", 3600, job_health_check))
        scheduler.add_job(Job("slo_review", 21600, job_slo_review))
        scheduler.add_job(Job("weekly_report", 604800, job_weekly_report))

    # إيقاف نظيف
    def signal_handler(sig, frame):
        print()
        print("Stopping...")
        scheduler.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    duration = args.duration if args.duration > 0 else None
    await scheduler.run(duration_seconds=duration)


if __name__ == "__main__":
    asyncio.run(main())
