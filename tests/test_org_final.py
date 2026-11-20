"""دفعة التغطية الأخيرة — فروع نادرة لكنها عقد معلن.

كل اختبار هنا مسار معلن في الكود حدث نادرًا: تخزين مكسور، مخطط
أحدث من الكود، موجات متوازية، أمر CLI بمهمة فاشلة، إلخ.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.org.agents import AgentRuntime, ToolRegistry
from src.org.contracts import (
    Approval,
    Claim,
    Evidence,
    Finding,
    Lesson,
    Mission,
    TaskResult,
)
from src.org.departments import DevelopmentDept, MissionContext
from src.org.learning import LessonsEngine
from src.org.metrics import OrgMetrics
from src.org.orchestrator import (
    ExecutiveOrchestrator,
    ExecutionPlan,
    PlanError,
    TaskSpec as _UnusedTaskSpec,  # noqa: F401 — استيراد صريح للعقد
)
from src.org.orchestrator import TaskSpec
from src.org.providers import ProviderConfig, ProviderPool
from src.org.repo_intel import ModuleInfo, RepoMap
from src.org.store import OrgError, OrgStore
from src.ops.store import OpsStore


class TestContractValidationBranches:
    def test_mission_negative_revision_loops(self) -> None:
        with pytest.raises(ValueError, match="revision_loops"):
            Mission(title="t", objective="o", revision_loops=-1)

    def test_finding_bad_status(self) -> None:
        with pytest.raises(ValueError, match="status"):
            Finding(mission_id="m", source="security", category="c",
                    severity="low", description="d", status="maybe")

    def test_evidence_detail_not_dict(self) -> None:
        with pytest.raises(ValueError, match="detail"):
            Evidence(mission_id="m", kind="log", detail="no")  # type: ignore[arg-type]

    def test_evidence_ok_not_bool(self) -> None:
        with pytest.raises(ValueError, match="ok"):
            Evidence(mission_id="m", kind="log", ok="yes")  # type: ignore[arg-type]

    def test_approval_approved_not_bool(self) -> None:
        with pytest.raises(ValueError, match="approved"):
            Approval(mission_id="m", kind="merge", subject="T",
                     approved="yes")  # type: ignore[arg-type]

    def test_lesson_negative_applied(self) -> None:
        with pytest.raises(ValueError, match="applied_count"):
            Lesson(text="t", scope="s", applied_count=-2)


class TestStoreEdgePaths:
    def test_rollback_on_constraint_error(self, tmp_path: Path) -> None:
        """خطأ قيد داخل المعاملة → تراجع كامل لا كتابة نصفية."""
        store = OrgStore(tmp_path / "s.db")
        m = store.create_mission(Mission(title="t", objective="o"))
        with pytest.raises(sqlite3.IntegrityError):
            with store._conn:  # noqa: SLF001 — اختبار مسار التراجع
                store._conn.execute(  # noqa: SLF001
                    "INSERT INTO missions (id, title, objective, phase, "
                    "status) VALUES (?, 'x', 'y', 'A_REQUIREMENTS', 'created')",
                    (m.id,))
        assert len(store.mission_list()) == 1

    def test_future_schema_rejected(self, tmp_path: Path) -> None:
        db = tmp_path / "future.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, "
                     "value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta VALUES ('org_schema_version', '99')")
        conn.commit()
        conn.close()
        with pytest.raises(OrgError, match="أحدث"):
            OrgStore(db)

    def test_mission_update_unknown(self, tmp_path: Path) -> None:
        store = OrgStore(":memory:")
        with pytest.raises(OrgError, match="غير موجودة"):
            store.mission_update(Mission(title="t", objective="o",
                                         id="org-m-ghost"))

    def test_mission_list_status_filter(self, tmp_path: Path) -> None:
        store = OrgStore(":memory:")
        store.create_mission(Mission(title="أ", objective="o1"))
        m2 = store.create_mission(Mission(title="ب", objective="o2"))
        store.mission_update(Mission(title=m2.title, objective=m2.objective,
                                     status="failed", id=m2.id))
        assert [m.id for m in store.mission_list(status="failed")] == [m2.id]

    def test_reviews_filters(self, tmp_path: Path) -> None:
        from src.org.contracts import Review
        store = OrgStore(":memory:")
        m = store.create_mission(Mission(title="t", objective="o"))
        for lens, rnd in (("logic", 0), ("security", 0), ("logic", 2)):
            store.add_review(Review(mission_id=m.id, task_id="t1",
                                    reviewer=f"review:{lens}", lens=lens,
                                    verdict="approve", score=85,
                                    debate_round=rnd))
        assert len(store.reviews_for(m.id, task_id="t1")) == 3
        assert len(store.reviews_for(m.id, task_id="t1", debate_round=2)) == 1

    def test_findings_status_filter(self, tmp_path: Path) -> None:
        store = OrgStore(":memory:")
        m = store.create_mission(Mission(title="t", objective="o"))
        f1 = store.add_finding(Finding(mission_id=m.id, source="security",
                                       category="c1", severity="low",
                                       description="d1"))
        store.add_finding(Finding(mission_id=m.id, source="security",
                                  category="c2", severity="low",
                                  description="d2"))
        store.finding_set_status(f1.id, "fixed")
        open_rows = store.findings_for(m.id, status="open")
        assert len(open_rows) == 1 and open_rows[0].id != f1.id

    def test_lesson_and_approval_with_explicit_id(self) -> None:
        store = OrgStore(":memory:")
        lesson = store.add_lesson(Lesson(text="t", scope="s", id="org-l-x"))
        assert lesson.id == "org-l-x"
        m = store.create_mission(Mission(title="t", objective="o"))
        approval = store.request_approval(Approval(
            mission_id=m.id, kind="merge", subject="T", id="org-a-x"))
        assert approval.id == "org-a-x"

    def test_close(self, tmp_path: Path) -> None:
        store = OrgStore(tmp_path / "c.db")
        store.close()  # إغلاق نظيف بلا خطأ


class TestOrchestratorEdgePaths:
    def test_parallel_wave_execution(self, tmp_path: Path) -> None:
        """موجة بمهمتين لنفس القسم تعمل بخيوط (مسار التوازي المعلن)."""
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        orch = ExecutiveOrchestrator(
            org, ops, pool=ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
            outdir=str(tmp_path))
        plan = ExecutionPlan(mission_id="m")
        plan.add("security", "scan", "فحص أول")
        plan.add("security", "scan", "فحص ثانٍ")
        m = org.create_mission(Mission(title="t", objective="o"))
        ctx = MissionContext(mission=m)
        orch._run_wave(plan, ctx, phase="E_TESTING", dept="security")
        rows = org.tasks_for_mission(m.id)
        assert all(r["state"] == "done" for r in rows)

    def test_unknown_dept_in_wave_raises(self, tmp_path: Path) -> None:
        """قسم بلا منفّذ في طوره → فشل صريح مسجّل لا صمت."""
        from src.org.departments import DepartmentError
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        orch = ExecutiveOrchestrator(
            org, ops, pool=ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
            outdir=str(tmp_path))
        m = org.create_mission(Mission(title="t", objective="o"))
        ctx = MissionContext(mission=m)
        orphan = TaskSpec(mission_id=m.id, dept="code_review", kind="council",
                          description="خارج تنفيذ الموجات",
                          id="org-t-orphan")
        org.add_task(orphan)
        with pytest.raises(DepartmentError, match="بلا منفّذ"):
            orch._execute_task(orphan, ctx)
        row = org.task_get(orphan.id)
        assert row is not None and row["state"] == "failed"

    def test_summarize_non_dict(self) -> None:
        from src.org.orchestrator import ExecutiveOrchestrator as E
        assert E._summarize(object()) == "object"

    def test_fail_unknown_mission_noop(self, tmp_path: Path) -> None:
        org = OrgStore(":memory:")
        ops = OpsStore(":memory:")
        orch = ExecutiveOrchestrator(
            org, ops, pool=ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
            outdir=str(tmp_path))
        orch._fail(Mission(title="t", objective="o", id="org-m-ghost"),
                   "سبب")  # بلا مهمة مخزنة — لا خطأ ولا كتابة

    def test_topological_cycle_raises(self) -> None:
        from dataclasses import replace
        plan = ExecutionPlan(mission_id="m")
        a = plan.add("qa", "test", "أ")
        b = plan.add("security", "scan", "ب")
        plan.tasks[0] = replace(plan.tasks[0], deps=[b.id])
        plan.tasks[1] = replace(plan.tasks[1], deps=[a.id])
        with pytest.raises(PlanError, match="لا موجات"):
            plan.topological()


class TestCliMissionCommand:
    def test_mission_fails_fast_on_missing_repo(
            self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from src.org.cli import main
        rc = main(["--db", str(tmp_path / "org.db"),
                   "--ops-db", str(tmp_path / "ops.db"),
                   "--outdir", str(tmp_path / "r"),
                   "mission", "--title", "t",
                   "--objective", "هدف غير قابل للتنفيذ",
                   "--repo", str(tmp_path / "no-repo")])
        assert rc == 1
        payload = __import__("json").loads(capsys.readouterr().out)
        assert payload["mission"]["status"] == "failed"


class TestRepoIntelEdges:
    def test_module_info_to_dict(self) -> None:
        info = ModuleInfo(rel_path="a/b.py", functions=["f"],
                          classes=["C"], imports=["os"], lines=3,
                          fingerprint="fp")
        data = info.to_dict()
        assert data["rel_path"] == "a/b.py" and data["classes"] == ["C"]

    def test_import_edges_skips_non_python(self) -> None:
        rm = RepoMap(root=".")
        rm.modules.append(ModuleInfo(rel_path="notes.md", imports=["x"]))
        rm.modules.append(ModuleInfo(rel_path="pkg/m.py", imports=["pkg.other"]))
        # ملف غير بايثون يُتخطى في الحواف وأسماء الوحدات
        assert all(src != "notes" for src, _ in rm.import_edges())
        assert rm.module_names() == ["pkg.m"]

    def test_graph_class_nodes(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text(
            "class C:\n    pass\n\n\nasync def a() -> None:\n    pass\n",
            encoding="utf-8")
        g = __import__("src.org.repo_intel",
                       fromlist=["RepoIntelligence"]) \
            .RepoIntelligence(tmp_path).scan().knowledge_graph()
        ids = {n["id"] for n in g["nodes"]}
        assert "class:m.py:C" in ids
        assert "func:m.py:async a" in ids

    def test_parse_import_variants(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text(
            "import os, json\nfrom . import sibling\n", encoding="utf-8")
        rm = __import__("src.org.repo_intel",
                        fromlist=["RepoIntelligence"]) \
            .RepoIntelligence(tmp_path).scan()
        mod = rm.modules[0]
        assert "os" in mod.imports and "json" in mod.imports
        assert mod.imports == ["os", "json"]  # from . بلا وحدة لا يُسجل

    def test_affected_skips_changed_importer(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text(
            "import b\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
        engine = __import__("src.org.repo_intel",
                            fromlist=["RepoIntelligence"]) \
            .RepoIntelligence(tmp_path)
        engine.scan()
        out = engine.affected_files(["a.py", "b.py"])
        assert out["transitive"] == []  # b مُغيَّر أصلاً فلا يُعاد


class TestSmallGaps:
    def test_metrics_regression_path(self, tmp_path: Path) -> None:
        org = OrgStore(":memory:")
        m = org.create_mission(Mission(title="t", objective="o"))
        spec = org.add_task(TaskSpec(mission_id=m.id, dept="qa",
                                     kind="test", description="d"))
        org.task_set_state(spec.id, "failed")
        assert OrgMetrics(org).regression_rate() == 1.0

    def test_pipeline_no_report_when_failed(self, tmp_path: Path) -> None:
        from src.org.pipeline import MissionPipeline
        pipeline = MissionPipeline(OrgStore(":memory:"), OpsStore(":memory:"),
                                   outdir=tmp_path / "r")
        report = pipeline.run(title="t", objective="o",
                              repo_path=str(tmp_path / "ghost"))
        assert report.report_path == "" and report.patch_path == ""

    def test_learning_empty_context(self, tmp_path: Path) -> None:
        engine = LessonsEngine(OrgStore(":memory:"))
        assert engine.planning_context() == "لا دروس نشطة بعد."
        assert isinstance(engine.heartbeat(), float)

    def test_function_hint_regex(self) -> None:
        assert DevelopmentDept._function_hint("دالة `compute` تُهيّئ",
                                              "m.py") == "compute"

    def test_security_requirements_detection(
            self, tmp_path: Path) -> None:
        from src.org.departments import SecurityDept
        from src.org.providers import ProviderPool
        from src.org.security import InjectionGuard
        from src.org.agents import AgentRuntime, ToolRegistry
        store = OrgStore(":memory:")
        m = store.create_mission(Mission(title="t", objective="o"))
        wt_path = tmp_path / "wt"
        wt_path.mkdir()
        (wt_path / "requirements.txt").write_text(
            "gunicorn==21.2.0\n", encoding="utf-8")
        ctx = MissionContext(mission=m)
        ctx.originals = {"requirements.txt": "gunicorn==21.2.0\n"}
        dept = SecurityDept(AgentRuntime(ProviderPool([ProviderConfig(name="mock", model="mock-1")]),
                                         ToolRegistry(), store),
                            InjectionGuard())
        out = dept.run(ctx)
        assert out["report"]["counts"]["vulnerable_dependencies"] == 1

    def test_verification_auditor_failure_ok(self, tmp_path: Path) -> None:
        """فشل رأي المُحقّق النموذجي لا يمنع الحسم الكودي."""
        from src.org.providers import ProviderError
        from src.org.sandbox import Worktree
        from src.org.verification import VerificationEngine

        class BoomPool(ProviderPool):
            def complete_with_fallback(self, messages, **kwargs):  # type: ignore[override]
                raise ProviderError("ميت")

        store = OrgStore(":memory:")
        runtime = AgentRuntime(BoomPool(), ToolRegistry(), store)
        engine = VerificationEngine(runtime, store, __import__(
            "src.org.sandbox", fromlist=["WorkspaceRunner"]).WorkspaceRunner())
        m = store.create_mission(Mission(title="t", objective="o"))
        claim = store.add_claim(Claim(mission_id=m.id, agent_role="r",
                                      statement="ملاحظة موثقة",
                                      claim_kind="observation"))
        store.add_evidence(Evidence(mission_id=m.id, kind="log", detail={},
                                    ok=True, claim_id=claim.id))
        wt = Worktree.from_source(tmp_path, files=[])
        try:
            report = engine.verify_mission(m, [claim], [], wt)
            assert report.verified == 1
        finally:
            wt.cleanup()

    def test_api_run_unknown_mission_404(self, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch
                                         ) -> None:
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.org.api import build_org_router
        monkeypatch.setenv("ORG_OPERATOR_TOKEN", "tok")
        app = FastAPI()
        app.include_router(build_org_router(OrgStore(tmp_path / "o.db"),
                                            OpsStore(tmp_path / "p.db"),
                                            outdir=str(tmp_path / "r")))
        http = TestClient(app)
        resp = http.post("/org/missions/nope/run",
                         headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 404

    def test_department_hint_guard_paths(self) -> None:
        assert DevelopmentDept._guard_hint("منع الصفر") == "القسمة على صفر"
        assert DevelopmentDept._guard_hint("empty inputs") == "مدخلات فارغة"
        assert DevelopmentDept._guard_hint("auth bypass") == "طلبات بلا تصريح"
        assert DevelopmentDept._guard_hint("negative values") == "قيم سالبة"
        assert DevelopmentDept._guard_hint("أي شيء") == "مدخلات غير صالحة"
