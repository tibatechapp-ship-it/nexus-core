"""اختبارات اللوحة وسطر الأوامر — حتمية، ملفات، أوامر معلنة.

القواعد المفروضة: نفس الحالة نفس نص التقرير حرفيًا، كل أمر CLI يعمل
بلا خادم ولا شبكة، وقرار الموافقة عبر CLI يتطلب اسم صانع القرار.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.org.cli import build_parser, main
from src.org.dashboard import OrgDashboard
from src.org.store import OrgStore
from src.ops.store import OpsStore


@pytest.fixture()
def org_store(tmp_path: Path) -> OrgStore:
    from src.org.contracts import Approval, Mission
    store = OrgStore(tmp_path / "org.db")
    m = store.create_mission(Mission(title="مهمة", objective="هدف"))
    # المشي القانوني عبر الآلة — لا قفز أطوار في الاختبار نفسه
    from src.org.contracts import MISSION_PHASES
    cur = m
    for phase in MISSION_PHASES[1:]:
        cur = store.mission_update(cur.with_phase(phase))
    store.mission_update(Mission(title=cur.title, objective=cur.objective,
                                 status="done", phase=cur.phase, id=cur.id))
    store.request_approval(Approval(mission_id=cur.id, kind="merge",
                                    subject="T-1"))
    return store


class TestDashboard:
    def test_report_deterministic(self, org_store: OrgStore) -> None:
        d1 = OrgDashboard(org_store).markdown_report()
        d2 = OrgDashboard(org_store).markdown_report()
        assert d1 == d2
        assert "المهام: 1" in d1

    def test_write_files(self, org_store: OrgStore,
                         tmp_path: Path) -> None:
        paths = OrgDashboard(org_store, outdir=tmp_path).write()
        snap = json.loads(Path(paths["snapshot"]).read_text(encoding="utf-8"))
        assert snap["missions_total"] == 1
        assert "المهام: 1" in Path(paths["report"]).read_text(
            encoding="utf-8")

    def test_snapshot_shape(self, org_store: OrgStore) -> None:
        snap = OrgDashboard(org_store).snapshot()
        for key in ("missions_total", "missions_by_phase",
                    "missions_by_status", "metrics_rates", "usage"):
            assert key in snap


class TestCLI:
    def test_parser_commands_declared(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        for cmd in ("mission", "show", "dashboard", "lessons", "metrics",
                    "approve"):
            assert cmd in help_text

    def test_metrics_command(self, org_store: OrgStore,
                             tmp_path: Path,
                             capsys: pytest.CaptureFixture[str]) -> None:
        db = str(org_store._path)  # noqa: SLF001 — مسار اختبار فقط
        rc = main(["--db", db, "--ops-db", str(tmp_path / "ops.db"),
                   "metrics"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert "completion_rate" in payload

    def test_dashboard_command(self, org_store: OrgStore,
                               tmp_path: Path,
                               capsys: pytest.CaptureFixture[str]) -> None:
        db = str(org_store._path)  # noqa: SLF001
        rc = main(["--db", db, "--ops-db", str(tmp_path / "ops.db"),
                   "--outdir", str(tmp_path / "r"), "dashboard"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["snapshot"]["missions_total"] == 1

    def test_show_command(self, org_store: OrgStore, tmp_path: Path,
                          capsys: pytest.CaptureFixture[str]) -> None:
        db = str(org_store._path)  # noqa: SLF001
        mission_id = org_store.mission_list()[0].id
        rc = main(["--db", db, "--ops-db", str(tmp_path / "ops.db"),
                   "show", mission_id])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["mission"]["id"] == mission_id

    def test_show_missing_mission(self, org_store: OrgStore,
                                  tmp_path: Path) -> None:
        db = str(org_store._path)  # noqa: SLF001
        rc = main(["--db", db, "--ops-db", str(tmp_path / "ops.db"),
                   "show", "nope"])
        assert rc == 2

    def test_approve_requires_actor(self, org_store: OrgStore,
                                    tmp_path: Path) -> None:
        db = str(org_store._path)  # noqa: SLF001
        approval = org_store.approvals_for(
            org_store.mission_list()[0].id)[0]
        rc = main(["--db", db, "--ops-db", str(tmp_path / "ops.db"),
                   "approve", approval.id, "--yes", "--by", "admin-human"])
        assert rc == 0
        decided = org_store.approvals_for(
            org_store.mission_list()[0].id)[0]
        assert decided.approved is True
        assert decided.decided_by == "admin-human"

    def test_lessons_command(self, org_store: OrgStore, tmp_path: Path,
                             capsys: pytest.CaptureFixture[str]) -> None:
        db = str(org_store._path)  # noqa: SLF001
        rc = main(["--db", db, "--ops-db", str(tmp_path / "ops.db"),
                   "lessons"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert "active_lessons" in payload


class TestOpsCliDelegation:
    def test_org_subcommand_exists(self) -> None:
        from src.ops.cli import _build_parser
        parser = _build_parser()
        assert "org" in parser.format_help()
