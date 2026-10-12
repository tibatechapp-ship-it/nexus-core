"""
TaskQueue - Priority task queue for workers
- Asyncio-safe with lock
- Priority-based ordering (lower = first)
- FIFO within same priority
- Snapshot for monitoring
"""
import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict

logger = logging.getLogger("queue")


@dataclass(order=True)
class Task:
    priority: int
    created_at: float = field(compare=False, default=0.0)
    id: str = field(compare=False, default="")
    kind: str = field(compare=False, default="review")
    path: str = field(compare=False, default="")
    content: str = field(compare=False, default="")
    result: dict = field(compare=False, default_factory=dict)


class TaskQueue:
    def __init__(self, max_size: int = 200):
        self._heap: List = []
        self._counter = 0
        self._max_size = max_size
        self._not_empty = asyncio.Event()
        self._lock = asyncio.Lock()
        self._stats = {"pushed": 0, "popped": 0, "rejected": 0}

    async def push(self, task: Task) -> bool:
        """Adds a task. Returns False if queue is full."""
        async with self._lock:
            if len(self._heap) >= self._max_size:
                self._stats["rejected"] += 1
                logger.warning("queue full, rejected task " + task.id)
                return False

            heapq.heappush(
                self._heap,
                (task.priority, task.created_at, self._counter, task)
            )
            self._counter += 1
            self._stats["pushed"] += 1
            self._not_empty.set()
            return True

    async def pop(self, timeout: float = 2.0) -> Optional[Task]:
        """Waits for a task, returns None on timeout."""
        try:
            await asyncio.wait_for(self._not_empty.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            if not self._heap:
                self._not_empty.clear()
                return None

            _, _, _, task = heapq.heappop(self._heap)
            self._stats["popped"] += 1

            if not self._heap:
                self._not_empty.clear()

            return task

    def size(self) -> int:
        return len(self._heap)

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def snapshot(self) -> List[Dict]:
        """Returns the top 10 tasks without removing them."""
        return [
            {"priority": t.priority, "id": t.id, "kind": t.kind, "path": t.path}
            for _, _, _, t in sorted(self._heap)[:10]
        ]

    def stats(self) -> Dict:
        return {
            "size": len(self._heap),
            "max_size": self._max_size,
            **self._stats,
        }

    def clear(self):
        """Clears all tasks."""
        self._heap.clear()
        self._not_empty.clear()


# Singleton
queue = TaskQueue(max_size=200)
