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
