"""خط أنابيب المهمة — واجهة واحدة لتشغيل التنظيم كاملًا وتجميع النواتج.

القواعد المعلنة:

* **تشغيل واحد = تقرير واحد**: كل مهمة تنتهي بتقرير هندسي على القرص
  ولقطة مقاييس ودروس مستخرجة — كلها من المخزن حتميًا.
* **لا توازٍ بين المهام العليا هنا**: المُنسّق يوازي داخل المهمة؛
  الخط أنابيب تسلسلي للمهام العليا — بساطة مقصودة لإمكانية التدقيق.
* **الفشل ناتج لا استثناء صامت**: مهمة فاشلة تُعاد حالتها ``failed``
  مع تقرير يوضح البوابة التي رفضت والسبب.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.org.contracts import Mission
from src.org.learning import LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.orchestrator import ExecutiveOrchestrator
from src.org.providers import ProviderPool
from src.org.store import OrgStore
from src.ops.store import OpsStore

__all__ = ["MissionPipeline", "PipelineReport"]


@dataclass(frozen=True)
class PipelineReport:
    """ناتج تشغيل خط الأنابيب — مهمة ومقاييس ودروس ومسارات ملفات."""

    mission: Mission
    metrics: dict[str, Any]
    lessons: list[str]
    report_path: str = ""
    patch_path: str = ""
    ticket_id: str = ""
    approval_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission": self.mission.to_dict(),
            "metrics": self.metrics,
            "lessons": self.lessons,
            "report_path": self.report_path,
            "patch_path": self.patch_path,
            "ticket_id": self.ticket_id,
            "approval_id": self.approval_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False,
                          indent=2)


class MissionPipeline:
    """خط أنابيب المهمة — تشغيل واحد من الهدف إلى التقرير والتذكرة."""

    def __init__(self, org_store: OrgStore, ops_store: OpsStore,
                 pool: ProviderPool | None = None,
                 outdir: str | Path = "reports/org") -> None:
        self.org_store = org_store
        self.ops_store = ops_store
        self.orchestrator = ExecutiveOrchestrator(
            org_store, ops_store, pool=pool, outdir=str(outdir))
        self.metrics = OrgMetrics(org_store)
        self.lessons = LessonsEngine(org_store)
        self.outdir = Path(outdir)

    def run(self, title: str, objective: str, repo_path: str = "", *,
            output_token_budget: int | None = None) -> PipelineReport:
        """تشغيل A→G مع سقف إخراج اختياري للمهمة ثم تجميع التقرير."""
        mission = Mission(title=title, objective=objective, repo_path=repo_path)
        mission = self.orchestrator.execute(
            mission, output_token_budget=output_token_budget)
        snap = self.metrics.snapshot()
        new_lessons = self.lessons.record_from_mission(mission.id)
        report_path = ""
        patch_path = ""
        ticket_id = ""
        approval_id = ""
        outdir = self.outdir / mission.id
        stored_report = outdir / "REPORT.md"
        if stored_report.exists():
            report_path = str(stored_report)
            patch = outdir / "patch.diff"
            patch_path = str(patch) if patch.exists() else ""
        approvals = self.org_store.approvals_for(mission.id)
        if approvals:
            approval_id = approvals[-1].id
            ticket_id = approvals[-1].subject
        self.org_store.record_metric("org.mission_status", 1.0
                                     if mission.status == "done" else 0.0,
                                     {"mission_id": mission.id})
        return PipelineReport(
            mission=mission, metrics=snap,
            lessons=[lesson.text for lesson in new_lessons],
            report_path=report_path, patch_path=patch_path,
            ticket_id=ticket_id, approval_id=approval_id)
