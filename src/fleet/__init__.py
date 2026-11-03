"""Fleet — الأسطول الموحد لكل وكلاء المستودع.

طبقة واحدة فوق الإطارين (novamind + الإطار الأساسي) ووحدات الجذر القديمة
تقدّم: جرداً موحّداً، فحص مطابقة، قياس أداء، وترتيباً معلناً. بلا شبكة،
بلا LLM حقيقي، بلا كتابة خارج ``reports/``.
"""

from __future__ import annotations

from src.fleet.record import AgentRecord, FRAMEWORKS
from src.fleet.inventory import build_inventory, reconcile, summary
from src.fleet.conformance import run_conformance
from src.fleet.benchmark import benchmark, rank, tier_of
from src.fleet.leaderboard import render_markdown, write_reports

__all__ = [
    "AgentRecord",
    "FRAMEWORKS",
    "build_inventory",
    "reconcile",
    "summary",
    "run_conformance",
    "benchmark",
    "rank",
    "tier_of",
    "render_markdown",
    "write_reports",
]
