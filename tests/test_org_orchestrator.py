"""اختبارات المُنسّق التنفيذي — الرسم والبوابات والفشل الصريح.

القواعد المفروضة: الرسم بلا دورة، الانتقال عبر البوابات فقط، فشل
القسم فشل مهمة معلن، ودورة المراجعة محدودة بعدد معلن لا حلقة لانهائية.
"""

from __future__ import annotations

import json

import pytest

from src.org.contracts import Mission
from src.org.departments import MissionContext
from src.org.recovery_context import save_mission_context_snapshot
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
        claimed_depts = {"executive", "repo_intel", "development",
                         "security", "qa", "release", "code_review",
                         "verification"}
        rows = [
            row for row in orchestrator.org_store.tasks_for_mission(mission.id)
            if row["dept"] in claimed_depts
        ]
        assert {row["dept"] for row in rows} == claimed_depts
        for row in rows:
            attempts = orchestrator.org_store.task_attempts_for(row["id"])
            assert len(attempts) == 1
            assert attempts[0]["status"] == "done"
            assert row["state"] == "done"
            assert orchestrator.org_store.claim_task(
                row["id"], worker_id="duplicate-gate-check") is None

    def test_illegal_phase_jump_via_store(
            self, orchestrator: ExecutiveOrchestrator) -> None:
        m = orchestrator.org_store.create_mission(
            Mission(title="t", objective="o"))
        with pytest.raises(OrgError):
            orchestrator.org_store.mission_update(
                m.with_phase("G_RELEASE"))

    def test_verification_exception_records_failed_claim(
            self, orchestrator: ExecutiveOrchestrator,
            monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_verification(*args: object, **kwargs: object) -> object:
            raise OrgError("verification backend unavailable")

        monkeypatch.setattr(
            orchestrator.verification, "verify_mission", fail_verification)
        mission = orchestrator.execute(Mission(
            title="تعطل بوابة التحقق",
            objective="تحقق من إصلاح تجريبي",
            repo_path="examples/org_demo/fixture_repo"))
        assert mission.status == "failed"
        verify_tasks = [
            row for row in orchestrator.org_store.tasks_for_mission(mission.id)
            if row["dept"] == "verification"
        ]
        assert len(verify_tasks) == 1
        assert verify_tasks[0]["state"] == "failed"
        attempts = orchestrator.org_store.task_attempts_for(verify_tasks[0]["id"])
        assert len(attempts) == 1
        assert attempts[0]["status"] == "failed"

    def test_missing_repo_fails_loudly(
            self, orchestrator: ExecutiveOrchestrator) -> None:
        mission = orchestrator.execute(Mission(
            title="t", objective="o", repo_path="/nonexistent/repo"))
        assert mission.status == "failed"
        rows = [r for r in orchestrator.org_store.tail_audit(20)
                if r["action"] == "mission.failed"]
        assert rows and rows[0]["details"]["reason"]
        failed_tasks = [
            row for row in orchestrator.org_store.tasks_for_mission(mission.id)
            if row["state"] == "failed"
        ]
        assert failed_tasks
        assert any(
            attempt["status"] == "failed"
            for row in failed_tasks
            for attempt in orchestrator.org_store.task_attempts_for(row["id"])
        )


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
            key=lambda row: int(json.loads(row["params"]).get("revision", 0)),
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

        # Each development revision receives an independent durable review.
        review_tasks = [
            row for row in org_store.tasks_for_mission(mission.id)
            if row["dept"] == "code_review"
        ]
        assert len(review_tasks) == 2
        for review_task in review_tasks:
            assert review_task["state"] == "done"
            attempts = org_store.task_attempts_for(review_task["id"])
            assert len(attempts) == 1
            assert attempts[0]["status"] == "done"
        review_rounds = [
            event for event in org_store.tail_audit(200)
            if event["action"] == "task.review_round_queued"
        ]
        assert len(review_rounds) == 1
        assert review_rounds[0]["details"]["round"] == 2
        assert review_rounds[0]["details"]["reviews_development_task_id"] == revisions[1]["id"]


class TestAuthorizedRetryDispatch:
    def test_authorized_retry_executes_only_replacement_task(
            self, orchestrator: ExecutiveOrchestrator,
            monkeypatch: pytest.MonkeyPatch) -> None:
        from src.org.departments import MissionContext
        from src.org.contracts import TaskSpec

        mission = orchestrator.org_store.create_mission(
            Mission(title="retry", objective="recover one failed task"))
        original = orchestrator.org_store.add_task(TaskSpec(
            mission_id=mission.id, dept="development", kind="implement",
            description="original implementation"))
        orchestrator.org_store.task_set_state(
            original.id, "failed", error="provider interruption")
        decision = orchestrator.org_store.reconcile_task(
            original.id, action="retry_authorized", actor="operator",
            reason="explicitly approved after inspecting the failure",
            decision_key="retry-development-1")
        replacement_id = str(decision["replacement_task_id"])
        calls: list[str] = []

        def run_development(ctx: MissionContext, dev_kind: str = "backend") -> dict[str, str]:
            calls.append(dev_kind)
            return {"status": "ok"}

        monkeypatch.setattr(orchestrator.depts.development, "run", run_development)
        result = orchestrator.execute_authorized_retry(
            replacement_id, MissionContext(mission=mission))

        assert result.task_id == replacement_id
        assert result.status == "done"
        assert calls == ["backend"]
        assert orchestrator.org_store.task_get(original.id)["state"] == "failed"
        assert orchestrator.org_store.task_get(replacement_id)["state"] == "done"
        assert len(orchestrator.org_store.task_attempts_for(replacement_id)) == 1
        assert orchestrator.org_store.task_attempts_for(replacement_id)[0]["status"] == "done"
        with pytest.raises(OrgError, match="ليست معلّقة"):
            orchestrator.execute_authorized_retry(
                replacement_id, MissionContext(mission=mission))

    def test_retry_dispatch_rejects_missing_operator_decision(
            self, orchestrator: ExecutiveOrchestrator) -> None:
        from src.org.departments import MissionContext
        from src.org.contracts import TaskSpec

        mission = orchestrator.org_store.create_mission(
            Mission(title="retry", objective="must not run without approval"))
        task = orchestrator.org_store.add_task(TaskSpec(
            mission_id=mission.id, dept="development", kind="implement",
            description="unapproved task"))
        with pytest.raises(OrgError, match="ليست إعادة محاولة مصرحًا بها"):
            orchestrator.execute_authorized_retry(
                task.id, MissionContext(mission=mission))
        assert orchestrator.org_store.task_get(task.id)["state"] == "pending"
        assert orchestrator.org_store.task_attempts_for(task.id) == []

    def test_retry_dispatch_waits_for_all_dependencies(
            self, orchestrator: ExecutiveOrchestrator) -> None:
        from src.org.departments import MissionContext
        from src.org.contracts import TaskSpec

        mission = orchestrator.org_store.create_mission(
            Mission(title="retry", objective="dependency gate"))
        dependency = orchestrator.org_store.add_task(TaskSpec(
            mission_id=mission.id, dept="repo_intel", kind="analyze",
            description="required prerequisite"))
        original = orchestrator.org_store.add_task(TaskSpec(
            mission_id=mission.id, dept="development", kind="implement",
            description="dependent implementation", deps=[dependency.id]))
        orchestrator.org_store.task_set_state(
            original.id, "failed", error="interrupted")
        decision = orchestrator.org_store.reconcile_task(
            original.id, action="retry_authorized", actor="operator",
            reason="approved after review", decision_key="retry-with-dep")

        with pytest.raises(OrgError, match="لم تكتمل بنجاح"):
            orchestrator.execute_authorized_retry(
                str(decision["replacement_task_id"]),
                MissionContext(mission=mission))
        assert orchestrator.org_store.task_get(
            str(decision["replacement_task_id"]))["state"] == "pending"
        assert orchestrator.org_store.task_attempts_for(
            str(decision["replacement_task_id"])) == []


class TestExplicitMissionResume:
    def test_resume_from_verification_skips_completed_work_and_runs_release(
            self, orchestrator: ExecutiveOrchestrator,
            tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        from pathlib import Path

        repo = Path("examples/org_demo/fixture_repo").resolve()
        state_root = Path(tmp_path) / "mission-state"  # type: ignore[arg-type]
        orchestrator.state_root = state_root
        mission = orchestrator.org_store.create_mission(Mission(
            title="resume at verification",
            objective="continue only the remaining release task",
            repo_path=str(repo), phase="F_VERIFICATION", status="running",
        ))
        plan = orchestrator.plan(mission)

        for task in plan.tasks:
            if task.dept == "release":
                continue
            claim = orchestrator.org_store.claim_task(
                task.id, worker_id="test-checkpoint-builder")
            assert claim is not None
            result = (
                {"verified": 2, "rejected": 0, "reproduced": True}
                if task.dept == "verification"
                else {"summary": f"completed:{task.dept}"}
            )
            orchestrator.org_store.finish_claimed_task(
                task.id, str(claim["lease_token"]), result)

        ctx = MissionContext(
            mission=mission,
            execution_policy={"schema_version": 1, "max_revision_loops": orchestrator.max_revision_loops},
        )
        save_mission_context_snapshot(
            orchestrator.org_store, ctx, state_root)
        saved = orchestrator.org_store.mission_context_snapshot_get(mission.id)
        assert saved is not None
        assert saved["payload"]["context"]["execution_policy"] == {
            "schema_version": 1, "max_revision_loops": orchestrator.max_revision_loops,
        }

        release_calls: list[str] = []

        def release(ctx: MissionContext) -> dict[str, str]:
            release_calls.append(ctx.mission.id)
            return {"status": "prepared"}

        monkeypatch.setattr(orchestrator.depts.release, "run", release)
        resumed = orchestrator.resume_mission(
            mission.id, actor="operator", reason="approved after reviewing checkpoint",
            expected_repo_root=repo)

        assert resumed.status == "done"
        assert resumed.phase == "G_RELEASE"
        assert release_calls == [mission.id]
        rows = orchestrator.org_store.tasks_for_mission(mission.id)
        by_dept = {row["dept"]: row for row in rows}
        assert by_dept["release"]["state"] == "done"
        assert len(orchestrator.org_store.task_attempts_for(
            by_dept["release"]["id"])) == 1
        for dept in (
            "executive", "repo_intel", "development", "code_review",
            "qa", "security", "verification",
        ):
            assert by_dept[dept]["state"] == "done"
            assert len(orchestrator.org_store.task_attempts_for(
                by_dept[dept]["id"])) == 1

    def test_resume_rejects_running_task_before_dispatch(
            self, orchestrator: ExecutiveOrchestrator,
            tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        from pathlib import Path

        repo = Path("examples/org_demo/fixture_repo").resolve()
        orchestrator.state_root = Path(tmp_path) / "mission-state"  # type: ignore[arg-type]
        mission = orchestrator.org_store.create_mission(Mission(
            title="blocked resume", objective="never replay uncertain work",
            repo_path=str(repo), phase="F_VERIFICATION", status="running",
        ))
        plan = orchestrator.plan(mission)
        for task in plan.tasks:
            if task.dept in {"release", "verification"}:
                continue
            claim = orchestrator.org_store.claim_task(
                task.id, worker_id="test-checkpoint-builder")
            assert claim is not None
            orchestrator.org_store.finish_claimed_task(
                task.id, str(claim["lease_token"]), {"done": True})
        verification = next(t for t in plan.tasks if t.dept == "verification")
        assert orchestrator.org_store.claim_task(
            verification.id, worker_id="interrupted-worker") is not None
        save_mission_context_snapshot(
            orchestrator.org_store, MissionContext(
                mission=mission,
                execution_policy={"schema_version": 1, "max_revision_loops": orchestrator.max_revision_loops},
            ), orchestrator.state_root)

        calls: list[str] = []
        monkeypatch.setattr(
            orchestrator.depts.release, "run",
            lambda ctx: calls.append(ctx.mission.id) or {"status": "unexpected"},
        )
        with pytest.raises(OrgError, match="غير مؤكدة|running"):
            orchestrator.resume_mission(
                mission.id, actor="operator", reason="approved after reviewing checkpoint",
                expected_repo_root=repo)
        assert calls == []
        assert orchestrator.org_store.task_get(verification.id)["state"] == "running"


    def test_resume_after_completed_review_uses_saved_verdict(
            self, orchestrator: ExecutiveOrchestrator,
            tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        from pathlib import Path
        from types import SimpleNamespace

        repo = Path("examples/org_demo/fixture_repo").resolve()
        orchestrator.state_root = Path(tmp_path) / "mission-state"  # type: ignore[arg-type]
        mission = orchestrator.org_store.create_mission(Mission(
            title="resume after review",
            objective="continue after durable review approval",
            repo_path=str(repo), phase="D_REVIEW", status="running",
        ))
        plan = orchestrator.plan(mission)
        development = next(t for t in plan.tasks if t.dept == "development")
        review = next(t for t in plan.tasks if t.dept == "code_review")

        for task in plan.tasks:
            if task.dept in {"qa", "security", "verification", "release"}:
                continue
            claim = orchestrator.org_store.claim_task(
                task.id, worker_id="test-checkpoint-builder")
            assert claim is not None
            result = (
                {"verdict": "approve", "development_task_id": development.id,
                 "mean": 95, "rounds": 1}
                if task.dept == "code_review"
                else {"summary": f"completed:{task.dept}"}
            )
            orchestrator.org_store.finish_claimed_task(
                task.id, str(claim["lease_token"]), result)

        ctx = MissionContext(
            mission=mission,
            execution_policy={"schema_version": 1, "max_revision_loops": orchestrator.max_revision_loops},
        )
        save_mission_context_snapshot(
            orchestrator.org_store, ctx, orchestrator.state_root)

        calls: list[str] = []

        def baseline(context: MissionContext) -> dict[str, bool]:
            calls.append("baseline")
            context.baseline_tests = {"baseline": True}
            return context.baseline_tests

        def patched(context: MissionContext) -> dict[str, bool]:
            calls.append("qa")
            context.patched_tests = {"patched": True}
            return context.patched_tests

        def security(context: MissionContext) -> dict[str, bool]:
            calls.append("security")
            return {"clean": True}

        def verify(*args: object, **kwargs: object) -> object:
            calls.append("verification")
            return SimpleNamespace(
                verified=1, rejected=0, reproduced_fix=True,
                to_dict=lambda: {"verified": 1, "rejected": 0},
            )

        def release(context: MissionContext) -> dict[str, str]:
            calls.append("release")
            return {"status": "prepared"}

        monkeypatch.setattr(orchestrator.depts.qa, "baseline", baseline)
        monkeypatch.setattr(orchestrator.depts.qa, "patched", patched)
        monkeypatch.setattr(orchestrator.depts.security, "run", security)
        monkeypatch.setattr(orchestrator.verification, "verify_mission", verify)
        monkeypatch.setattr(orchestrator.depts.release, "run", release)

        resumed = orchestrator.resume_mission(
            mission.id, actor="operator", reason="approved after reviewing checkpoint",
            expected_repo_root=repo)

        assert resumed.status == "done"
        assert resumed.phase == "G_RELEASE"
        assert calls == ["baseline", "qa", "security", "verification", "release"]
        assert orchestrator.org_store.task_get(review.id)["state"] == "done"
        assert len(orchestrator.org_store.task_attempts_for(review.id)) == 1
