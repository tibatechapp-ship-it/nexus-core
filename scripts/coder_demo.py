#!/usr/bin/env python3
"""End-to-end demo: the five-stage coder engine on a scripted backend.

عرض تجريبي بلا شبكة (بند G5/التشغيل): محرك المراحل الخمس يعمل من الطرف
إلى الطرف على موصل مبرمج الإجابات — تحليل، اكتشاف، مخطط معلن، تنفيذ معزول،
بوابة جودة خضراء. المخرج JSON واحد والحالة 0 عند النجاح فقط.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.coder.engine import run_engine  # noqa: E402 — demo bootstrap


class ScriptedConnector:
    """Minimal BYOK-shape connector with scripted replies (no network)."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        return self.replies.pop(0) if self.replies else {"ok": False, "error": "exhausted"}


def _build_replies() -> list:
    defects = json.dumps([
        {"file": "checkout.py", "description": "total() ignores empty cart",
         "severity": "high"}])
    plan = json.dumps({
        "goal": "fix empty-cart total in checkout demo",
        "defects": ["total() crashes on empty cart"],
        "steps": [
            {"file": "checkout.py", "action": "create", "reason": "cart logic under test",
             "patch_hint": "def total(prices: list) -> int:\n    return sum(prices)\n",
             "risk": "low"},
            {"file": "test_checkout.py", "action": "create", "reason": "prove the fix",
             "patch_hint": ("from checkout import total\n\n\n"
                            "def test_empty_cart() -> None:\n    assert total([]) == 0\n\n\n"
                            "def test_items() -> None:\n    assert total([2, 3]) == 5\n"),
             "risk": "low"},
        ],
        "tests_to_run": ["test_checkout.py"],
    })
    return [{"ok": True, "reply": defects}, {"ok": True, "reply": plan}]


async def main() -> int:
    """Run the engine once on a temp workspace and print the JSON verdict."""
    repo = REPO  # analyzed read-only for the stage-1 map
    workdir = Path(tempfile.mkdtemp(prefix="coder-demo-"))
    result: dict = await run_engine(
        "fix empty-cart total in checkout demo",
        ScriptedConnector(_build_replies()),
        root=repo,
        workdir=workdir,
        max_iterations=2,
        gates=[[sys.executable, "-m", "pytest", "-q", "--no-header", "--maxfail=3"]],
        test_timeout=120,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
