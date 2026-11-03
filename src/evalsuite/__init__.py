"""Internal eval suite (M3.2) — 50 tasks over the five-stage coding engine.

جناح التقييم الداخلي: كتالوج 50 مهمة بأربع فئات، موصل بلا شبكة للحل
المرجعي، عدّاء معزول لكل مهمة، وتقرير آلي بمعدلات النجاح والأزمنة
والانحدارات مقارنة بالتشغيل السابق.
"""

from __future__ import annotations

from src.evalsuite.offline import OfflineConnector, offline_factory
from src.evalsuite.report import summarize
from src.evalsuite.runner import default_gate, prepare_workdir, run_suite, run_task
from src.evalsuite.tasks import (
    CATEGORIES,
    COUNTS,
    Task,
    by_category,
    catalog,
    get_task,
    plan_for,
)

__all__ = [
    "CATEGORIES",
    "COUNTS",
    "OfflineConnector",
    "Task",
    "by_category",
    "catalog",
    "default_gate",
    "get_task",
    "offline_factory",
    "plan_for",
    "prepare_workdir",
    "run_suite",
    "run_task",
    "summarize",
]
