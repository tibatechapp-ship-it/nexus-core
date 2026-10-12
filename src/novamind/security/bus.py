"""MessageBus — تواصل بين الوكلاء."""
import asyncio
from collections import defaultdict
from typing import Callable, Any, Optional
import logging

log = logging.getLogger("MessageBus")


class MessageBus:
    """نظام pub/sub بين الوكلاء."""

    def __init__(self):
        self._subscribers: dict = defaultdict(list)
        self._history: list = []

    def subscribe(self, topic: str, callback: Callable):
        self._subscribers[topic].append(callback)

    async def publish(self, topic: str, message: Any):
        self._history.append({"topic": topic, "msg": message})
        self._history = self._history[-100:]

        for cb in self._subscribers.get(topic, []):
            try:
                res = cb(message)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                log.warning(f"Subscriber failed for {topic}: {e}")

    async def send_to_agent(self, agent_name: str, task: dict):
        await self.publish(f"agent:{agent_name}", task)

    def get_history(self, topic: Optional[str] = None):
        if topic:
            return [h for h in self._history if h["topic"] == topic]
        return list(self._history)


_bus: Optional[MessageBus] = None


def get_bus() -> MessageBus:
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus
