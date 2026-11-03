"""Fleet — الأسطول الموحد لكل وكلاء المستودع.

طبقة واحدة فوق الإطارين (novamind + الإطار الأساسي) ووحدات الجذر القديمة
تقدّم: جرداً موحّداً، فحص مطابقة، قياس أداء، وترتيباً معلناً. بلا شبكة،
بلا LLM حقيقي، بلا كتابة خارج ``reports/``.
"""

from __future__ import annotations

from src.fleet.record import AgentRecord, FRAMEWORKS
from src.fleet.inventory import build_inventory, reconcile, summary
from src.fleet.conformance import run_conformance, check_agent
from src.fleet.benchmark import benchmark, rank, tier_of, SCORE_WEIGHTS
from src.fleet.leaderboard import render_markdown, write_reports

__all__ = [
    "AgentRecord",
    "FRAMEWORKS",
    "build_inventory",
    "reconcile",
    "summary",
    "run_conformance",
    "check_agent",
    "benchmark",
    "rank",
    "tier_of",
    "SCORE_WEIGHTS",
    "render_markdown",
    "write_reports",
]
