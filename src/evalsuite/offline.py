"""Offline connector — replays each task's reference solution with no network.

الموصل بلا شبكة (M3.2): يعيد كشف عيوب فارغاً ثم الخطة المرجعية للمهمة، فيثبت
سلامة خط الأنابيب كاملاً (محرك ← صندوق ← بوابة) دون أي نموذج حقيقي. لا يصلح
مقياساً لجودة النموذج — له تُستخدم موصلات glm الحقيقية عبر CLI.
"""

from __future__ import annotations

import json
from typing import Any

from src.evalsuite.tasks import Task, plan_for


class OfflineConnector:
    """BYOK-shaped connector double with canned per-task replies."""

    def __init__(self, task: Task) -> None:
        self._replies: list[str] = [
            "[]",  # stage 2 (detect): no model-side defects
            json.dumps(plan_for(task), ensure_ascii=False),
        ]
        self.calls: list[str] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        """Return the next scripted reply; record every prompt (audit)."""
        self.calls.append(prompt)
        if not self._replies:
            return {"ok": False, "error": "offline script exhausted"}
        return {"ok": True, "reply": self._replies.pop(0)}


def offline_factory(task: Task) -> Any:
    """Factory handed to ``run_suite`` — one fresh connector per task."""
    return OfflineConnector(task)
