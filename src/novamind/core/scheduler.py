"""
Scheduler - Task scheduling engine
Runs tasks every N seconds/minutes/hours
"""
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("scheduler")


class ScheduledTask:
    def __init__(self, name: str, interval: int,
                 callback: Callable, run_immediately: bool = True):
        self.name = name
        self.interval = interval  # seconds
        self.callback = callback
        self.last_run = 0
        self.runs = 0
        self.failures = 0
        self.last_error = ""
        if run_immediately:
            self.last_run = time.time() - interval  # run now


class Scheduler:
    def __init__(self):
        self.tasks: List[ScheduledTask] = []
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def add_task(self, name: str, interval: int,
                 callback: Callable,
                 run_immediately: bool = True):
        task = ScheduledTask(name, interval, callback, run_immediately)
        self.tasks.append(task)
        logger.info(f"scheduled task '{name}' every {interval}s")
        return task

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"scheduler started with {len(self.tasks)} tasks")

    def stop(self):
        self.running = False
        self._stop_event.set()

    def _run_loop(self):
        while self.running and not self._stop_event.is_set():
            now = time.time()
            for task in self.tasks:
                if now - task.last_run >= task.interval:
                    try:
                        logger.debug(f"running task '{task.name}'")
                        task.callback()
                        task.runs += 1
                        task.last_run = time.time()
                    except Exception as e:
                        task.failures += 1
                        task.last_error = str(e)[:200]
                        logger.error(f"task '{task.name}' failed: {e}")

            # Sleep in small increments for responsiveness
            self._stop_event.wait(1)

    def stats(self) -> Dict:
        now = time.time()
        return {
            "running": self.running,
            "tasks": [
                {
                    "name": t.name,
                    "interval": t.interval,
                    "runs": t.runs,
                    "failures": t.failures,
                    "last_run": t.last_run,
                    "next_run_in": max(0, t.interval - (now - t.last_run)),
                    "last_error": t.last_error,
                }
                for t in self.tasks
            ],
        }


scheduler = Scheduler()
