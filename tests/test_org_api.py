"""اختبارات واجهة REST للتنظيم — مصادقة حسّاسة وقراءة مفتوحة.

القواعد المفروضة: بدون توكن مشغّل لا إنشاء ولا تشغيل ولا قرار، والتوكن
الخاطئ 401، والقراءة العامة للوحة والمهام تعمل، و404 صريح للمجهول.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi اختيارية (novamind)")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.org.api import build_org_router  # noqa: E402
from src.org.store import OrgStore  # noqa: E402
from src.ops.store import OpsStore  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path,
           monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, OrgStore]]:
    monkeypatch.setenv("ORG_OPERATOR_TOKEN", "operator-token-123")
    org = OrgStore(tmp_path / "org.db")
    ops = OpsStore(tmp_path / "ops.db")
    app = FastAPI()
    app.include_router(build_org_router(org, ops, outdir=str(tmp_path / "r")))
    yield TestClient(app), org


AUTH = {"Authorization": "Bearer operator-token-123"}


class TestReadEndpoints:
    def test_dashboard_open(self, client: tuple[TestClient, OrgStore]) -> None:
        http, _ = client
        resp = http.get("/org/dashboard")
        assert resp.status_code == 200
        assert "missions_total" in resp.json()

    def test_missions_list_open(self,
                                client: tuple[TestClient, OrgStore]) -> None:
        http, _ = client
        assert http.get("/org/missions").status_code == 200

    def test_report_text(self, client: tuple[TestClient, OrgStore]) -> None:
        http, _ = client
        resp = http.get("/org/dashboard/report")
        assert resp.status_code == 200
        assert "لوحة" in resp.json()["report"]

    def test_unknown_mission_404(self,
                                 client: tuple[TestClient, OrgStore]) -> None:
        http, _ = client
        assert http.get("/org/missions/nope").status_code == 404


class TestWriteEndpointsAuth:
    def test_create_mission_requires_token(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        resp = http.post("/org/missions", json={
            "title": "t", "objective": "o"})
        assert resp.status_code == 401
        assert org.mission_list() == []

    def test_wrong_token_401(self, client: tuple[TestClient, OrgStore]) -> None:
        http, _ = client
        resp = http.post("/org/missions", json={"title": "t",
                                                "objective": "o"},
                         headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_create_mission_with_token(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        resp = http.post("/org/missions", json={"title": "مهمة",
                                                "objective": "هدف"},
                         headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["title"] == "مهمة"
        assert len(org.mission_list()) == 1

    def test_create_mission_persists_output_token_limit(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        resp = http.post("/org/missions", json={
            "title": "bounded API", "objective": "cap",
            "output_token_limit": 12000,
        }, headers=AUTH)
        assert resp.status_code == 200
        mission_id = resp.json()["id"]
        assert resp.json()["output_token_limit"] == 12000
        budget = org.mission_token_budget_get(mission_id)
        assert budget is not None and budget["output_token_limit"] == 12000

    @pytest.mark.parametrize("invalid", [True, 0, -1, "12000", 2**63])
    def test_create_mission_rejects_invalid_output_token_limit(
            self, client: tuple[TestClient, OrgStore], invalid: object) -> None:
        http, org = client
        resp = http.post("/org/missions", json={
            "title": "invalid API", "objective": "must reject",
            "output_token_limit": invalid,
        }, headers=AUTH)
        assert resp.status_code == 422
        assert org.mission_list() == []

    def test_run_endpoint_requires_explicit_execution_policy(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        created = http.post("/org/missions", json={
            "title": "run policy", "objective": "must provide execution authority",
        }, headers=AUTH)
        mission_id = created.json()["id"]
        response = http.post(
            f"/org/missions/{mission_id}/run", headers=AUTH)
        assert response.status_code == 422
        stored = org.mission_get(mission_id)
        assert stored is not None and stored.status == "created"

    def test_run_uses_the_approved_existing_mission(
            self, client: tuple[TestClient, OrgStore],
            monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace
        from src.org.pipeline import MissionPipeline

        http, org = client
        created = http.post("/org/missions", json={
            "title": "same mission", "objective": "retain approval identity",
            "repo_path": "fixture",
        }, headers=AUTH)
        mission_id = created.json()["id"]
        captured: dict[str, object] = {}

        def fake_run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(to_dict=lambda: {"mission_id": mission_id})

        monkeypatch.setattr(MissionPipeline, "run", fake_run)
        response = http.post(
            f"/org/missions/{mission_id}/run",
            json={"execution_mode": "process", "trusted_local": True},
            headers=AUTH,
        )
        assert response.status_code == 200
        assert captured["existing_mission"].id == mission_id
        assert len(org.mission_list()) == 1

    def test_container_execution_approval_is_image_bound(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        created = http.post("/org/missions", json={
            "title": "container approval", "objective": "run safely",
        }, headers=AUTH)
        assert created.status_code == 200
        mission_id = created.json()["id"]
        image = "registry.example/nexus-runner@sha256:" + "a" * 64
        requested = http.post(
            f"/org/missions/{mission_id}/approvals/run-untrusted",
            json={"container_image": image}, headers=AUTH)
        assert requested.status_code == 200
        approval_id = requested.json()["approval_id"]
        approval = org.approvals_for(mission_id)[0]
        assert approval.id == approval_id
        assert approval.kind == "run_untrusted"
        assert approval.subject == image
        assert approval.approved is None

        decided = http.post(
            f"/org/approvals/{approval_id}/decide",
            json={"approved": True, "decided_by": "operator"}, headers=AUTH)
        assert decided.status_code == 200
        assert org.approvals_for(mission_id)[0].approved is True

    def test_container_execution_approval_rejects_mutable_image(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        created = http.post("/org/missions", json={
            "title": "mutable image", "objective": "must reject",
        }, headers=AUTH)
        mission_id = created.json()["id"]
        response = http.post(
            f"/org/missions/{mission_id}/approvals/run-untrusted",
            json={"container_image": "registry.example/runner:latest"},
            headers=AUTH)
        assert response.status_code == 422
        assert org.approvals_for(mission_id) == []

    def test_decide_approval_requires_token(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        from src.org.contracts import Approval, Mission
        m = org.create_mission(Mission(title="t", objective="o"))
        a = org.request_approval(Approval(mission_id=m.id, kind="merge",
                                          subject="T-1"))
        resp = http.post(f"/org/approvals/{a.id}/decide",
                         json={"approved": True, "decided_by": "h"})
        assert resp.status_code == 401
        assert org.approvals_for(m.id)[0].approved is None

    def test_decide_approval_with_token(
            self, client: tuple[TestClient, OrgStore]) -> None:
        http, org = client
        from src.org.contracts import Approval, Mission
        m = org.create_mission(Mission(title="t", objective="o"))
        a = org.request_approval(Approval(mission_id=m.id, kind="merge",
                                          subject="T-1"))
        resp = http.post(f"/org/approvals/{a.id}/decide",
                         json={"approved": True, "decided_by": "admin"},
                         headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["decided_by"] == "admin"


class TestAvailability:
    def test_available_flag_matches_env(self) -> None:
        from src.org.api import org_router_available
        assert org_router_available() is True

    def test_no_token_env_returns_503(self, tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ORG_OPERATOR_TOKEN", raising=False)
        org = OrgStore(tmp_path / "o.db")
        ops = OpsStore(tmp_path / "p.db")
        app = FastAPI()
        app.include_router(build_org_router(org, ops, outdir=str(tmp_path)))
        http = TestClient(app)
        resp = http.post("/org/missions", json={"title": "t",
                                                "objective": "o"},
                         headers={"Authorization": "Bearer anything"})
        assert resp.status_code == 503
