"""اختبارات المُنسّق التنفيذي — الرسم والبوابات والفشل الصريح.

القواعد المفروضة: الرسم بلا دورة، الانتقال عبر البوابات فقط، فشل
القسم فشل مهمة معلن، ودورة المراجعة محدودة بعدد معلن لا حلقة لانهائية.
"""

from __future__ import annotations

import pytest

from src.org.contracts import Mission
from src.org.orchestrator import ExecutiveOrchestrator, PlanError
from src.org.providers import ProviderConfig, ProviderPool
from src.org.store import OrgError, OrgStore
from src.ops.store import OpsStore


@pytest.fixture()
def org_store() -> OrgStore:
    return OrgStore(":memory:")


@pytest.fixture()
def ops_store() -> OpsStore:
    return OpsStore(":memory:")


@pytest.fixture()
def orchestrator(org_store: OrgStore, ops_store: OpsStore,
                 tmp_path: object) -> ExecutiveOrchestrator:
    return ExecutiveOrchestrator(
        org_store, ops_store,
        pool=ProviderPool([ProviderConfig()]),
        outdir=str(tmp_path),  # type: ignore[arg-type]
        max_revision_loops=1)


class TestPlan:
    def test_plan_covers_all_phases(self, orchestrator:
                                    ExecutiveOrchestrator) -> None:
        m = orchestrator.org_store.create_mission(
            Mission(title="t", objective="o"))
        plan = orchestrator.plan(m)
        depts = {t.dept for t in plan.tasks}
        assert {"executive", "repo_intel", "development", "security",
                "code_review", "qa", "verification", "release"} <= depts

    def test_plan_tasks_persisted(self, orchestrator:
                                  ExecutiveOrchestrator) -> None:
        m = orchestrator.org_store.create_mission(
            Mission(title="t", objective="o"))
        plan = orchestrator.plan(m)
        rows = orchestrator.org_store.tasks_for_mission(m.id)
        assert len(rows) == len(plan.tasks)

    def test_topological_waves(self, orchestrator:
                               ExecutiveOrchestrator) -> None:
        m = orchestrator.org_store.create_mission(
            Mission(title="t", objective="o"))
        plan = orchestrator.plan(m)
        waves = plan.topological()
        assert waves and waves[0][0].dept == "executive"
        release_wave = waves[-1]
        assert release_wave[0].dept == "release"

    def test_cyclic_plan_rejected(self) -> None:
        from dataclasses import replace

        from src.org.orchestrator import ExecutionPlan
        plan = ExecutionPlan(mission_id="m")
        a = plan.add("qa", "test", "أ")
        b = plan.add("security", "scan", "ب")
        # فرض دورة كاملة: أ ينتظر ب وب ينتظر أ
        plan.tasks[0] = replace(plan.tasks[0], deps=[b.id])
        plan.tasks[1] = replace(plan.tasks[1], deps=[a.id])
        with pytest.raises(PlanError, match="دوري"):
            plan.validate()

    def test_missing_dep_rejected(self) -> None:
        from src.org.orchestrator import ExecutionPlan
        plan = ExecutionPlan(mission_id="m")
        plan.add("qa", "test", "أ", deps=["org-t-ghost"])
        with pytest.raises(PlanError, match="غير موجودة"):
            plan.validate()


class TestPhaseGates:
    def test_execute_walks_phases_in_order(
            self, orchestrator: ExecutiveOrchestrator,
            tmp_path: object) -> None:
        mission = orchestrator.execute(Mission(
            title="حارس قسمة",
            objective=("أضف حارس قسمة على صفر إلى دالة divide في وحدة "
                       "calc.mathops مع اختبارات للحدية"),
            repo_path="examples/org_demo/fixture_repo"))
        assert mission.phase == "G_RELEASE"
        assert mission.status == "done"

    def test_illegal_phase_jump_via_store(
            self, orchestrator: ExecutiveOrchestrator) -> None:
        m = orchestrator.org_store.create_mission(
            Mission(title="t", objective="o"))
        with pytest.raises(OrgError):
            orchestrator.org_store.mission_update(
                m.with_phase("G_RELEASE"))

    def test_missing_repo_fails_loudly(
            self, orchestrator: ExecutiveOrchestrator) -> None:
        mission = orchestrator.execute(Mission(
            title="t", objective="o", repo_path="/nonexistent/repo"))
        assert mission.status == "failed"
        rows = [r for r in orchestrator.org_store.tail_audit(20)
                if r["action"] == "mission.failed"]
        assert rows and rows[0]["details"]["reason"]


class TestRevisionLoop:
    def test_revision_loops_recorded(
            self, org_store: OrgStore, ops_store: OpsStore,
            tmp_path: object) -> None:
        """فشل المراجعة يعيد التطوير حتى السقف ثم فشل معلن بعدّاد."""
        from src.org.providers import MockProvider

        class TodoDevProvider(MockProvider):
            def _dev_reply(self, prompt: str) -> str:
                import json
                base = json.loads(super()._dev_reply(prompt))
                for c in base["changed_files"]:
                    c["content"] += "\n# TODO: لاحقًا\n"
                return json.dumps(base, ensure_ascii=False)

        pool = ProviderPool([ProviderConfig()])
        original_get = pool.get

        def patched_get(name: str = "", model: str = "") -> object:
            prov = original_get(name, model)
            if isinstance(prov, MockProvider):
                prov.__class__ = TodoDevProvider
            return prov

        pool.get = patched_get  # type: ignore[method-assign]
        orch = ExecutiveOrchestrator(
            org_store, ops_store, pool=pool, outdir=str(tmp_path),  # type: ignore[arg-type]
            max_revision_loops=1)
        mission = orch.execute(Mission(
            title="دورة مراجعة",
            objective=("أضف حارس قسمة على صفر إلى دالة divide في وحدة "
                       "calc.mathops مع اختبارات"),
            repo_path="examples/org_demo/fixture_repo"))
        assert mission.status == "failed"
        assert mission.revision_loops >= 1

        # كل دورة تطوير لها سجل مستقل؛ لا نعيد فتح المهمة المنتهية.
        development_tasks = [
            row for row in org_store.tasks_for_mission(mission.id)
            if row["dept"] == "development"
        ]
        assert len(development_tasks) == 2
        revisions = sorted(
            (row for row in development_tasks),
            key=lambda row: int(__import__("json").loads(row["params"]).get(
                "revision", 0)),
        )
        assert revisions[0]["state"] == "done"
        assert revisions[1]["state"] == "done"
        for row in revisions:
            attempts = org_store.task_attempts_for(row["id"])
            assert len(attempts) == 1
            assert attempts[0]["status"] == "done"
        queued = [
            event for event in org_store.tail_audit(100)
            if event["action"] == "task.revision_queued"
        ]
        assert len(queued) == 1
        assert queued[0]["details"]["supersedes_task_id"] == revisions[0]["id"]
