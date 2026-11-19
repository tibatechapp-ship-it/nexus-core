"""واجهة REST للتنظيم — راوتر FastAPI اختياري بنفس عقود المتجر.

القواعد المعلنة:

* **اختياري الصراحة**: هذه الطبقة تحتاج ``fastapi`` (حزمة novamind
  الاختيارية) — النواة stdlib تعمل بلاها كاملة عبر CLI. الاستيراد
  محمي والفشل رسالة معلنة لا انهيار.
* **القراءة مفتوحة والحسّاس مصرّح**: قراءة اللوحة والمهام مفتوحة؛
  قرار الموافقة البشرية وبدء تشغيل مهمة يتطلبان توكن مشغّل معلن من
  البيئة (``ORG_OPERATOR_TOKEN``) — التوكن لا يُسجَّل ولا يُطبع.
* **لا دمج ذاتي من الواجهة**: نقطة الموافقة تسجّل قرارًا بشريًا فقط —
  الدمج الفعلي عبر تذكرة الطبقة التشغيلية وبوابة بشرية معلنة.
"""

from __future__ import annotations

import os
from typing import Any

from src.org.contracts import Approval, Mission
from src.org.dashboard import OrgDashboard
from src.org.pipeline import MissionPipeline
from src.org.store import OrgStore
from src.ops.store import OpsStore

__all__ = ["build_org_router", "org_router_available"]

try:  # pragma: no cover — حزمة اختيارية قد تغيب في نواة Termux
    from fastapi import APIRouter, Header, HTTPException
    from pydantic import BaseModel, Field, StrictInt

    _FASTAPI_OK = True
except ImportError:  # pragma: no cover
    _FASTAPI_OK = False


def org_router_available() -> bool:
    """هل راوتر التنظيم متاح في هذه البيئة؟"""
    return _FASTAPI_OK


if _FASTAPI_OK:

    class MissionIn(BaseModel):
        """مُدخل إنشاء مهمة — عنوان وهدف ومستودع."""

        title: str
        objective: str
        repo_path: str = ""
        output_token_limit: StrictInt | None = Field(
            default=None, gt=0, le=2**63 - 1)

    class ExecutionPolicyIn(BaseModel):
        """Explicit execution authority supplied for each mission run."""

        execution_mode: str
        trusted_local: bool = False
        container_enabled: bool = False
        container_image: str = ""
        approval_id: str = ""

    class ContainerApprovalIn(BaseModel):
        """Request a human approval bound to one immutable container image."""

        container_image: str

    class ApprovalIn(BaseModel):
        """مُدخل قرار موافقة — قرار واسم صانع القرار إلزاميًا."""

        approved: bool
        decided_by: str

    def build_org_router(org_store: OrgStore, ops_store: OpsStore,
                         outdir: str = "reports/org") -> Any:
        """بناء راوتر التنظيم — نقاط معلنة بمصادقة حسّاسة فقط."""
        router = APIRouter(prefix="/org", tags=["org"])
        pipeline = MissionPipeline(org_store, ops_store, outdir=outdir)
        dashboard = OrgDashboard(org_store, outdir=outdir)

        def _require_operator(
                authorization: str | None = Header(default=None)) -> None:
            token = os.environ.get("ORG_OPERATOR_TOKEN", "")
            if not token:
                raise HTTPException(
                    status_code=503,
                    detail="المصادقة غير مهيأة — ORG_OPERATOR_TOKEN مطلوب")
            if authorization != f"Bearer {token}":
                raise HTTPException(status_code=401, detail="توكن مشغّل غير صالح")

        @router.get("/dashboard")
        def org_dashboard() -> dict[str, Any]:
            return dashboard.snapshot()

        @router.get("/dashboard/report")
        def org_dashboard_report() -> dict[str, str]:
            return {"report": dashboard.markdown_report()}

        @router.get("/missions")
        def list_missions() -> list[dict[str, Any]]:
            return [m.to_dict() for m in org_store.mission_list()]

        @router.get("/missions/{mission_id}")
        def get_mission(mission_id: str) -> dict[str, Any]:
            mission = org_store.mission_get(mission_id)
            if mission is None:
                raise HTTPException(status_code=404, detail="مهمة غير موجودة")
            return mission.to_dict()

        @router.post("/missions")
        def create_mission(payload: MissionIn,
                           authorization: str | None = Header(default=None)
                           ) -> dict[str, Any]:
            _require_operator(authorization)
            mission = org_store.create_mission(
                Mission(title=payload.title, objective=payload.objective,
                        repo_path=payload.repo_path,
                        output_token_limit=payload.output_token_limit))
            return mission.to_dict()

        @router.post("/missions/{mission_id}/approvals/run-untrusted")
        def request_container_approval(
                mission_id: str, payload: ContainerApprovalIn,
                authorization: str | None = Header(default=None)
                ) -> dict[str, Any]:
            _require_operator(authorization)
            mission = org_store.mission_get(mission_id)
            if mission is None:
                raise HTTPException(status_code=404, detail="مهمة غير موجودة")
            image = payload.container_image
            digest = image.rsplit("@sha256:", 1)[-1] if "@sha256:" in image else ""
            if (len(digest) != 64
                    or any(ch not in "0123456789abcdefABCDEF" for ch in digest)):
                raise HTTPException(
                    status_code=422,
                    detail="container_image must be pinned to a sha256 digest")
            approval = org_store.request_approval(Approval(
                mission_id=mission.id, kind="run_untrusted", subject=image,
                note="Authorize execution only inside this immutable container image",
            ))
            return {
                "approval_id": approval.id, "kind": approval.kind,
                "subject": approval.subject, "approved": approval.approved,
            }

        @router.post("/missions/{mission_id}/run")
        def run_mission(mission_id: str, payload: ExecutionPolicyIn,
                        authorization: str | None = Header(default=None)
                        ) -> dict[str, Any]:
            _require_operator(authorization)
            mission = org_store.mission_get(mission_id)
            if mission is None:
                raise HTTPException(status_code=404, detail="مهمة غير موجودة")
            report = pipeline.run(title=mission.title,
                                  objective=mission.objective,
                                  repo_path=mission.repo_path,
                                  output_token_limit=mission.output_token_limit,
                                  execution_policy=payload.dict(exclude_unset=True))
            return report.to_dict()

        @router.post("/approvals/{approval_id}/decide")
        def decide_approval(approval_id: str, payload: ApprovalIn,
                            authorization: str | None = Header(default=None)
                            ) -> dict[str, Any]:
            _require_operator(authorization)
            approval = org_store.decide_approval(
                approval_id, payload.approved, payload.decided_by)
            return {
                "id": approval.id, "approved": approval.approved,
                "decided_by": approval.decided_by,
                "decided_at": approval.decided_at,
            }

        return router
