#!/usr/bin/env python3
"""تشغيل وكيل واحد من الأسطول — تحميل من السجل واستدعاء مهارته.

يعمل بلا مفاتيح: مولّد mock محلي حتمي يُبطّن الموجّه (نفس أسلوب
لوحة التحكم) — الأنسب للتعليم لأنه يُظهر الحيلة بوضوح.

    python3 examples/02_agent_run.py
"""

from __future__ import annotations


import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("NEXUS_ALLOW_OPEN", "1")
os.environ.setdefault("NOVAMIND_HOME", str(ROOT))


def patch_mock_router() -> None:
    """بطّن موجّه LLM بمولّد حتمي — بلا شبكة بلا مفاتيح."""
    from novamind.core.llm_router import LLMRouter

    def mock_gen(self: Any, prompt: str = "", system: str = "",
                 **kw: Any) -> dict[str, Any]:
        # المُبرمج يطلب «Python code فقط» — نردّ كودًا خامًا صالحًا.
        code = "def add(a, b):\n    return a + b\n"
        return {"ok": True, "text": code,
                "provider": "mock", "model": "mock", "elapsed": 0.01}

    LLMRouter.generate = mock_gen
    LLMRouter.generate_for_task = lambda self, *a, **kw: mock_gen(self, *a, **kw)


def main() -> int:
    # مجلد عمل المُبرمج (تنفيذ الكود المولَّد بأمان في tmp).
    Path("/tmp/novamind_workspace").mkdir(parents=True, exist_ok=True)
    patch_mock_router()

    from src.fleet.report import build_inventory

    inventory = build_inventory()
    print(f"الأسطول: {len(inventory)} وكيلًا موحّدًا")
    names = sorted({rec.name for rec in inventory})
    print("عيّنة:", ", ".join(names[:8]), "…")

    # السجل الحي يحمّل الوكيل بالاسم (lazy import لكل وكيل).
    from nova.registry import REGISTRY

    agent = REGISTRY.load_agent("coder")
    print("\nالوكيل:", type(agent).__name__)
    outcome = agent.build("اصنع دالة بايثون تجمع رقمين")
    ok = bool(outcome.get("ok")) if isinstance(outcome, dict) else False
    print("نجاح:", ok)
    print("الكود الناتج:")
    print(outcome.get("code", ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
