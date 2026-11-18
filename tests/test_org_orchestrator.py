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


class TestProcessInterruptionRecovery:
    def test_reconstructs_orchestrator_from_durable_verification_checkpoint(
            self, tmp_path: object) -> None:
        """A fresh orchestrator continues after a durable gate checkpoint."""
        from pathlib import Path

        root = Path(tmp_path)  # type: ignore[arg-type]
        repo = Path("examples/org_demo/fixture_repo").resolve()
        database = root / "org.sqlite3"
        state_root = root / "mission-state"
        first_store = OrgStore(database)
        first = ExecutiveOrchestrator(
            first_store, OpsStore(":memory:"),
            pool=ProviderPool([ProviderConfig()]),
            outdir=str(root / "first-run"), max_revision_loops=1,
            state_root=state_root,
        )
        mission = first_store.create_mission(Mission(
            title="process restart recovery",
            objective="continue from a durable verification checkpoint",
            repo_path=str(repo), phase="F_VERIFICATION", status="running",
        ))
        plan = first.plan(mission)

        # Model termination after verification was durably recorded but before
        # the orchestrator advanced the mission to the release phase.
        for task in plan.tasks:
            if task.dept == "release":
                continue
            claim = first_store.claim_task(
                task.id, worker_id="interrupted-process-checkpoint")
            assert claim is not None
            result = (
                {"verified": 2, "rejected": 0, "reproduced": True}
                if task.dept == "verification"
                else {"summary": f"completed:{task.dept}"}
            )
            first_store.finish_claimed_task(
                task.id, str(claim["lease_token"]), result)

        save_mission_context_snapshot(
            first_store,
            MissionContext(
                mission=mission,
                execution_policy={
                    "schema_version": 1,
                    "max_revision_loops": first.max_revision_loops,
                },
            ),
            state_root,
        )
        checkpoint = first_store.mission_context_snapshot_get(mission.id)
        assert checkpoint is not None
        assert checkpoint["payload"]["context"]["execution_policy"] == {
            "schema_version": 1, "max_revision_loops": 1,
        }
        initial_tasks = first_store.tasks_for_mission(mission.id)
        mission_id = mission.id

        # Close through the store's public lifecycle API, then construct a
        # completely new store and orchestrator against the same SQLite file.
        first_store.close()
        second_store = OrgStore(database)
        second = ExecutiveOrchestrator(
            second_store, OpsStore(":memory:"),
            pool=ProviderPool([ProviderConfig()]),
            outdir=str(root / "second-run"), max_revision_loops=99,
            state_root=state_root,
        )
        release_calls: list[str] = []

        def release(context: MissionContext) -> dict[str, str]:
            release_calls.append(context.mission.id)
            return {"status": "prepared"}

        second.depts.release.run = release

        resumed = second.resume_mission(
            mission_id, actor="operator",
            reason="resume after the previous process stopped",
            expected_repo_root=repo,
        )

        assert resumed.status == "done"
        assert resumed.phase == "G_RELEASE"
        assert release_calls == [mission_id]
        final_tasks = second_store.tasks_for_mission(mission_id)
        final_by_id = {row["id"]: row for row in final_tasks}
        assert set(final_by_id) == {row["id"] for row in initial_tasks}
        assert all(row["state"] == "done" for row in final_tasks)
        assert all(
            len(second_store.task_attempts_for(row["id"])) == 1
            for row in final_tasks
        )
        runs = second_store.mission_resume_runs_for(mission_id)
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        latest = second_store.mission_context_snapshot_get(mission_id)
        assert latest is not None
        assert latest["payload"]["context"]["execution_policy"] == {
            "schema_version": 1, "max_revision_loops": 1,
        }


class TestSubprocessMissionCrashRecovery:
    def test_recovers_after_first_process_exits_abruptly(
            self, tmp_path: object) -> None:
        """A separate OS process resumes SQLite state after os._exit()."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        root = Path(tmp_path)  # type: ignore[arg-type]
        project_root = Path(__file__).resolve().parents[1]
        repo = (project_root / "examples/org_demo/fixture_repo").resolve()
        database = root / "org.sqlite3"
        state_root = root / "mission-state"
        marker = root / "first-process-stopped.json"
        result_file = root / "resume-result.json"

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(project_root), str(project_root / "src"),
             env.get("PYTHONPATH", "")])
        env.update({
            "NEXUS_TEST_DB": str(database),
            "NEXUS_TEST_STATE": str(state_root),
            "NEXUS_TEST_REPO": str(repo),
            "NEXUS_TEST_MARKER": str(marker),
            "NEXUS_TEST_RESULT": str(result_file),
        })

        bootstrap = r'''
import json
import os
from pathlib import Path
from src.org.contracts import Mission
from src.org.departments import MissionContext
from src.org.orchestrator import ExecutiveOrchestrator
from src.org.providers import ProviderConfig, ProviderPool
from src.org.recovery_context import save_mission_context_snapshot
from src.org.store import OrgStore
from src.ops.store import OpsStore

db = Path(os.environ["NEXUS_TEST_DB"])
state = Path(os.environ["NEXUS_TEST_STATE"])
repo = Path(os.environ["NEXUS_TEST_REPO"])
store = OrgStore(db)
orchestrator = ExecutiveOrchestrator(
    store, OpsStore(":memory:"), pool=ProviderPool([ProviderConfig()]),
    outdir=str(db.parent / "first-run"), max_revision_loops=1,
    state_root=state,
)
mission = store.create_mission(Mission(
    title="subprocess crash recovery",
    objective="resume from durable verification checkpoint",
    repo_path=str(repo), phase="F_VERIFICATION", status="running",
))
plan = orchestrator.plan(mission)
for task in plan.tasks:
    if task.dept == "release":
        continue
    claim = store.claim_task(task.id, worker_id="crashed-os-process")
    assert claim is not None
    result = (
        {"verified": 2, "rejected": 0, "reproduced": True}
        if task.dept == "verification"
        else {"summary": "durably completed:" + task.dept}
    )
    store.finish_claimed_task(task.id, str(claim["lease_token"]), result)

save_mission_context_snapshot(
    store,
    MissionContext(mission=mission, execution_policy={
        "schema_version": 1, "max_revision_loops": 1,
    }),
    state,
)
Path(os.environ["NEXUS_TEST_MARKER"]).write_text(
    json.dumps({
        "mission_id": mission.id,
        "task_ids": [task.id for task in plan.tasks],
    }),
    encoding="utf-8",
)
# Deliberately bypass Python cleanup: the OS terminates this process while
# SQLite has already committed every durable write above.
os._exit(73)
'''
        first = subprocess.run(
            [sys.executable, "-c", bootstrap],
            cwd=project_root, env=env, capture_output=True, text=True,
            timeout=60, check=False,
        )
        assert first.returncode == 73, first.stderr
        assert marker.is_file()
        checkpoint = json.loads(marker.read_text(encoding="utf-8"))
        mission_id = checkpoint["mission_id"]
        expected_task_ids = set(checkpoint["task_ids"])

        resume_script = r'''
import json
import os
from pathlib import Path
from src.org.orchestrator import ExecutiveOrchestrator
from src.org.providers import ProviderConfig, ProviderPool
from src.org.store import OrgStore
from src.ops.store import OpsStore

db = Path(os.environ["NEXUS_TEST_DB"])
state = Path(os.environ["NEXUS_TEST_STATE"])
repo = Path(os.environ["NEXUS_TEST_REPO"])
store = OrgStore(db)
orchestrator = ExecutiveOrchestrator(
    store, OpsStore(":memory:"), pool=ProviderPool([ProviderConfig()]),
    outdir=str(db.parent / "second-run"), max_revision_loops=99,
    state_root=state,
)
release_calls = []
def prepare_release(context):
    release_calls.append(context.mission.id)
    return {"status": "prepared"}
orchestrator.depts.release.run = prepare_release
mission_id = json.loads(
    Path(os.environ["NEXUS_TEST_MARKER"]).read_text(encoding="utf-8")
)["mission_id"]
mission = orchestrator.resume_mission(
    mission_id, actor="operator",
    reason="resume after abrupt operating-system process exit",
    expected_repo_root=repo,
)
Path(os.environ["NEXUS_TEST_RESULT"]).write_text(
    json.dumps({
        "status": mission.status,
        "phase": mission.phase,
        "release_calls": release_calls,
    }),
    encoding="utf-8",
)
store.close()
'''
        second = subprocess.run(
            [sys.executable, "-c", resume_script],
            cwd=project_root, env=env, capture_output=True, text=True,
            timeout=60, check=False,
        )
        assert second.returncode == 0, second.stderr
        resumed = json.loads(result_file.read_text(encoding="utf-8"))
        assert resumed == {
            "status": "done",
            "phase": "G_RELEASE",
            "release_calls": [mission_id],
        }

        recovered_store = OrgStore(database)
        try:
            final_tasks = recovered_store.tasks_for_mission(mission_id)
            assert {row["id"] for row in final_tasks} == expected_task_ids
            assert all(row["state"] == "done" for row in final_tasks)
            assert all(
                len(recovered_store.task_attempts_for(row["id"])) == 1
                for row in final_tasks
            )
            runs = recovered_store.mission_resume_runs_for(mission_id)
            assert len(runs) == 1
            assert runs[0]["status"] == "completed"
        finally:
            recovered_store.close()


class TestCheckpointLedgerDrift:
    def test_task_commit_without_matching_context_checkpoint_fails_closed(
            self, tmp_path: object) -> None:
        """A task commit newer than its snapshot must never dispatch on resume."""
        from pathlib import Path

        root = Path(tmp_path)  # type: ignore[arg-type]
        repo = Path("examples/org_demo/fixture_repo").resolve()
        database = root / "org.sqlite3"
        state_root = root / "mission-state"

        first_store = OrgStore(database)
        first = ExecutiveOrchestrator(
            first_store, OpsStore(":memory:"),
            pool=ProviderPool([ProviderConfig()]),
            outdir=str(root / "first-run"), state_root=state_root,
        )
        mission = first_store.create_mission(Mission(
            title="checkpoint boundary",
            objective="detect a committed task newer than its context snapshot",
            repo_path=str(repo), phase="A_REQUIREMENTS", status="running",
        ))
        plan = first.plan(mission)
        save_mission_context_snapshot(
            first_store,
            MissionContext(mission=mission, execution_policy={
                "schema_version": 1, "max_revision_loops": 2,
            }),
            state_root,
        )

        # Simulate a crash after the task result commits but before the
        # subsequent context snapshot can bind to this new ledger revision.
        requirements = next(task for task in plan.tasks
                            if task.dept == "executive")
        claim = first_store.claim_task(
            requirements.id, worker_id="interrupted-after-task-commit")
        assert claim is not None
        first_store.finish_claimed_task(
            requirements.id, str(claim["lease_token"]),
            {"summary": "requirements committed"},
        )
        first_store.close()

        second_store = OrgStore(database)
        second = ExecutiveOrchestrator(
            second_store, OpsStore(":memory:"),
            pool=ProviderPool([ProviderConfig()]),
            outdir=str(root / "second-run"), state_root=state_root,
        )
        before = second_store.tasks_for_mission(mission.id)
        with pytest.raises(OrgError, match="سجل المهام تغيّر بعد آخر checkpoint"):
            second.resume_mission(
                mission.id, actor="operator",
                reason="inspect task-commit/context-checkpoint crash boundary",
                expected_repo_root=repo,
            )

        after = second_store.tasks_for_mission(mission.id)
        assert {row["id"]: row["state"] for row in after} == {
            row["id"]: row["state"] for row in before
        }
        assert all(
            len(second_store.task_attempts_for(row["id"])) ==
            (1 if row["id"] == requirements.id else 0)
            for row in after
        )
        resume_runs = second_store.mission_resume_runs_for(mission.id)
        assert len(resume_runs) == 1
        assert resume_runs[0]["status"] == "failed"
        assert not any(
            event["action"] == "mission.resume_started"
            for event in second_store.tail_audit(100)
        )
        second_store.close()
