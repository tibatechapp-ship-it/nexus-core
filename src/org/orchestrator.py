"""المُنسّق التنفيذي — رسم مهام الأقسام الثمانية وتنفيذه ببوابات معلنة.

القواعد المعلنة:

* **رسم حتمي (DAG)**: خطة المهمة تُبنى مهامها وتبعياتها بترتيب معلن —
  نفس الهدف يعطي نفس الرسم، ودورة في التبعيات مرفوضة في البناء.
* **الطور يتحرك عبر آلة الحالات فقط**: كل انتقال يمر بمتجر التنظيم
  (``ALLOWED_PHASE_TRANSITIONS``) — لا قفز أطوار ولا اختصار بوابات.
* **تنفيذ موازٍ للمنفصلات فقط**: المهام المستقلة تُنفَّذ بخيوط بمستوى
  تزامن معلن؛ ما يعتمد على شيء ينتظر نجاحه — فشل التبعية يُسقط
  المتعطل عليها (``skipped``) لا يخمّن نتيجته.
* **دورة مراجعة محدودة**: فشل المراجعة يعيد التطوير حتى
  ``max_revision_loops`` — تجاوز السقف فشل صريح بمخاطر موثّقة لا صمت.
* **كل شيء يُدقَّق**: إنشاء مهمة، انتقال طور، نتيجة قسم — سطر تدقيق
  في المتجر غير قابل للحذف.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from src.org.contracts import (
    ALLOWED_PHASE_TRANSITIONS,
    Finding,
    Mission,
    TaskResult,
    TaskSpec,
    new_id,
)
from src.org.departments import (
    Departments,
    DepartmentError,
    MissionContext,
)
from src.org.providers import ProviderPool
from src.org.recovery import assess_mission_resume
from src.org.recovery_context import (
    restore_mission_context,
    save_mission_context_snapshot,
)
from src.org.store import OrgError, OrgStore
from src.org.verification import VerificationEngine
from src.ops.store import OpsStore

__all__ = ["ExecutionPlan", "ExecutiveOrchestrator", "PlanError"]

#: مستوى التزامن المعلن — خيوط التنفيذ الموازي للمنفصلات.
MAX_WORKERS = 4

#: أطوار تعمل بالتوازي داخلها مهام الأقسام — البوابات تسلسلية.
PARALLEL_PHASES = frozenset({"D_REVIEW", "E_TESTING"})


class PlanError(RuntimeError):
    """خطأ خطة — رسم دوري أو مهمة بلا تبعيات صالحة."""


@dataclass
class ExecutionPlan:
    """خطة تنفيذ مهمة — مهام معلنة بتبعيات صحيحة ودورة مرفوضة."""

    mission_id: str
    tasks: list[TaskSpec] = field(default_factory=list)

    def add(self, dept: str, kind: str, description: str,
            deps: list[str] | None = None,
            params: dict[str, Any] | None = None) -> TaskSpec:
        spec = TaskSpec(mission_id=self.mission_id, dept=dept, kind=kind,
                        description=description, deps=deps or [],
                        params=params or {})
        spec = spec.with_id(new_id("org-t", self.mission_id, dept, kind,
                                   description))
        self.tasks.append(spec)
        return spec

    def validate(self) -> None:
        """فحص الرسم — معرّفات تبعيات موجودة ولا دورة."""
        ids = {t.id for t in self.tasks}
        for t in self.tasks:
            for dep in t.deps:
                if dep not in ids:
                    raise PlanError(
                        f"تبعية غير موجودة: {t.id} → {dep}")
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        """كشف دورة بترتيب طوبولوجي كامل — بقايا تعني دورة."""
        deps_left = {t.id: set(t.deps) for t in self.tasks}
        done: set[str] = set()
        while deps_left:
            ready = [tid for tid, deps in deps_left.items()
                     if deps <= done]
            if not ready:
                raise PlanError("رسم تنفيذ دوري — خطة مرفوضة")
            for tid in ready:
                deps_left.pop(tid)
                done.add(tid)

    def topological(self) -> list[list[TaskSpec]]:
        """موجات تنفيذ حتمية — كل موجة مستقلة داخليًا (توازي ممكن)."""
        deps_left = {t.id: set(t.deps) for t in self.tasks}
        by_id = {t.id: t for t in self.tasks}
        waves: list[list[TaskSpec]] = []
        done: set[str] = set()
        while deps_left:
            ready_ids = sorted(
                tid for tid, deps in deps_left.items() if deps <= done)
            if not ready_ids:
                raise PlanError("رسم تنفيذ دوري — لا موجات")
            waves.append([by_id[tid] for tid in ready_ids])
            for tid in ready_ids:
                deps_left.pop(tid)
                done.add(tid)
        return waves


class ExecutiveOrchestrator:
    """المُنسّق التنفيذي — يخطط ويفوض ويتتبع ويحسم الصراع ويدقّق."""

    def __init__(self, org_store: OrgStore, ops_store: OpsStore,
                 pool: ProviderPool | None = None,
                 outdir: str = "reports/org",
                 max_workers: int = MAX_WORKERS,
                 max_revision_loops: int = 2,
                 state_root: str | Path | None = None) -> None:
        self.org_store = org_store
        self.ops_store = ops_store
        self.depts = Departments(pool or ProviderPool(), org_store,
                                 ops_store, outdir)
        self.verification = VerificationEngine(
            self.depts.runtime, org_store, self.depts.runner)
        self.max_workers = max_workers
        self.max_revision_loops = max_revision_loops
        self.state_root = Path(state_root or Path.home() / ".nexus-core" / "missions")

    # ── التخطيط ───────────────────────────────────────────────────────────

    def plan(self, mission: Mission) -> ExecutionPlan:
        """خطة حتمية A→G — كل طور مهامه وتبعياته معلنة."""
        plan = ExecutionPlan(mission_id=mission.id)
        t_req = plan.add("executive", "requirements",
                         "تحليل الهدف ومعايير القبول")
        t_intel = plan.add("repo_intel", "analyze",
                           "مسح المستودع وخريطة التأثير", deps=[t_req.id])
        t_dev = plan.add("development", "implement",
                         "توليد الرقعة في نسخة عمل معزولة",
                         deps=[t_intel.id],
                         params={"dev_kind": "backend"})
        t_sec = plan.add("security", "scan", "أسرار وتبعيات وحقن وتهديد",
                         deps=[t_dev.id])
        t_review = plan.add("code_review", "council",
                            "مجلس مراجعة بعدسات مستقلة", deps=[t_dev.id])
        t_test = plan.add("qa", "test",
                          "أساس قبل الرقعة واختبارات بعدها داخل العزل",
                          deps=[t_dev.id])
        t_verify = plan.add("verification", "verify",
                            "حسم الادعاءات وإعادة إنتاج الإصلاح",
                            deps=[t_review.id, t_test.id, t_sec.id])
        plan.add("release", "prepare",
                 "فرع ورقعة وتقرير وتذكرة بموافقة بشرية", deps=[t_verify.id])
        plan.validate()
        self.org_store.audit("plan.built", mission.id,
                             {"tasks": len(plan.tasks)})
        for spec in plan.tasks:
            self.org_store.add_task(spec)
        return plan

    # ── التنفيذ ───────────────────────────────────────────────────────────

    def execute(self, mission: Mission) -> Mission:
        """تنفيذ كامل A→G — بوابات الأطوار عبر المتجر، فشل صريح لا صمت."""
        mission = self.org_store.create_mission(mission)
        mission = self.org_store.mission_update(
            mission.with_phase("A_REQUIREMENTS"))
        self.org_store.mission_update(
            Mission(title=mission.title, objective=mission.objective,
                    repo_path=mission.repo_path,
                    acceptance_criteria=mission.acceptance_criteria,
                    status="running", id=mission.id))
        ctx = MissionContext(mission=mission)
        plan = self.plan(mission)
        try:
            self._run_wave(plan, ctx, phase="A_REQUIREMENTS",
                           dept="executive")
            self._advance_phase(mission, "A_REQUIREMENTS", "B_INTEL")
            self._run_wave(plan, ctx, phase="B_INTEL", dept="repo_intel")
            self._advance_phase(mission, "B_INTEL", "C_DEVELOP")
            self._run_wave(plan, ctx, phase="C_DEVELOP", dept="development")
            # بوابة المراجعة مع دورة إصلاح محدودة
            loops = 0
            review_round = 0
            while True:
                review_round += 1
                if review_round > 1:
                    previous_dev = max(
                        (task for task in plan.tasks
                         if task.dept == "development"),
                        key=lambda task: int(task.params.get("revision", 0)),
                    )
                    self._queue_review_round(plan, previous_dev, review_round)
                    self._checkpoint_context(ctx)
                self._advance_phase(mission, self._current_phase(mission),
                                    "D_REVIEW")
                review_ok = self._run_review_gate(plan, ctx)
                if review_ok:
                    break
                loops += 1
                self._bump_revision_loops(mission)
                if loops > self.max_revision_loops:
                    self._fail(mission,
                               "تجاوز سقف دورات المراجعة — مخاطر موثّقة")
                    return self._final(mission, ctx, failed=True)
                self._advance_phase(mission, "D_REVIEW", "C_DEVELOP")
                previous_dev = max(
                    (task for task in plan.tasks if task.dept == "development"),
                    key=lambda task: int(task.params.get("revision", 0)),
                )
                self._queue_development_revision(plan, previous_dev, loops)
                self._checkpoint_context(ctx)
                self._run_wave(plan, ctx, phase="C_DEVELOP", dept="development")
            self._advance_phase(mission, "D_REVIEW", "E_TESTING")
            self._run_wave(plan, ctx, phase="E_TESTING", dept="qa")
            self._run_wave(plan, ctx, phase="E_TESTING", dept="security")
            self._advance_phase(mission, "E_TESTING", "F_VERIFICATION")
            verify_ok = self._run_verification_gate(mission, plan, ctx)
            if not verify_ok:
                self._fail(mission, "بوابة التحقق رفضت الأدلة")
                return self._final(mission, ctx, failed=True)
            self._advance_phase(mission, "F_VERIFICATION", "G_RELEASE")
            self._run_wave(plan, ctx, phase="G_RELEASE", dept="release")
            mission = self._final(mission, ctx, failed=False)
            return mission
        except (DepartmentError, OrgError, PlanError) as exc:
            self._fail(mission, f"فشل تنفيذ: {type(exc).__name__}: {exc}")
            return self._final(mission, ctx, failed=True,
                               error=str(exc))
        finally:
            if ctx.worktree is not None and mission.status in ("done", "failed"):
                # نسخة العمل المؤقتة تُحذف بعد جمع الأدلة والرقعة والتقرير
                ctx.worktree.cleanup()

    # ── موجات التنفيذ ─────────────────────────────────────────────────────

    def _run_wave(self, plan: ExecutionPlan, ctx: MissionContext,
                  phase: str, dept: str) -> None:
        """تنفيذ المهام المعلّقة فقط؛ المطالبة الذرية تحسم التنافس."""
        wave = [
            task for task in plan.tasks
            if task.dept == dept
            and (self.org_store.task_get(task.id) or {}).get("state") == "pending"
        ]
        if not wave:
            return
        if len(wave) == 1:
            self._execute_task(wave[0], ctx)
            return
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._execute_task, task, ctx): task
                       for task in wave}
            for future in as_completed(futures):
                future.result()

    def _queue_development_revision(
            self, plan: ExecutionPlan, previous: TaskSpec,
            revision: int) -> TaskSpec:
        """إنشاء مهمة تطوير جديدة مرتبطة بسابقتها بدل إعادة فتح سجل منتهٍ."""
        if revision < 1:
            raise OrgError("رقم مراجعة التطوير يجب أن يكون موجبًا")
        spec = plan.add(
            "development", "implement",
            f"إعادة تطوير بعد رفض المراجعة — revision {revision}",
            deps=[previous.id],
            params={
                **previous.params,
                "revision": revision,
                "supersedes_task_id": previous.id,
            },
        )
        self.org_store.add_task(spec)
        self.org_store.audit(
            "task.revision_queued", spec.id,
            {"revision": revision, "supersedes_task_id": previous.id},
        )
        return spec

    def _execute_task(self, spec: TaskSpec, ctx: MissionContext) -> TaskResult:
        """تنفيذ مطالبة دائمة؛ لا يبدأ التنفيذ دون lease مسجلة."""
        claim = self.org_store.claim_task(
            spec.id, worker_id=f"nexus-orchestrator:{spec.dept}")
        if claim is None:
            raise OrgError(f"المهمة غير معلّقة أو مملوكة لعامل آخر: {spec.id}")
        lease_token = str(claim["lease_token"])
        t0 = time.time()
        try:
            if spec.dept == "executive":
                out = self.depts.requirements.run(ctx)
                self._store_criteria(ctx.mission, out)
            elif spec.dept == "repo_intel":
                out = self.depts.intel.run(ctx)
            elif spec.dept == "development":
                out = self.depts.development.run(
                    ctx, dev_kind=str(spec.params.get("dev_kind", "backend")))
            elif spec.dept == "security":
                out = self.depts.security.run(ctx)
            elif spec.dept == "qa":
                if not ctx.baseline_tests:
                    self.depts.qa.baseline(ctx)
                out = self.depts.qa.patched(ctx)
            elif spec.dept == "release":
                out = self.depts.release.run(ctx)
            else:
                raise DepartmentError(f"قسم بلا منفّذ في هذا الطور: {spec.dept}")
            self._persist_claims(ctx)
            summary = self._summarize(out)
            result = TaskResult(
                task_id=spec.id, dept=spec.dept, status="done",
                output={"summary": summary},
                attempts=int(claim.get("attempts", 1)),
                duration_ms=round((time.time() - t0) * 1000, 2))
        except Exception as exc:  # noqa: BLE001 — الفشل يُسجَّل ثم يُرفع
            self.org_store.fail_claimed_task(
                spec.id, lease_token, f"{type(exc).__name__}: {exc}")
            raise
        self.org_store.finish_claimed_task(
            spec.id, lease_token, result.output)
        self._checkpoint_context(ctx)
        return result

    def execute_authorized_retry(
            self, replacement_task_id: str,
            ctx: MissionContext) -> TaskResult:
        """تنفيذ إعادة محاولة أنشأها قرار مشغّل صريح فقط.

        لا يكتشف المهام تلقائيًا ولا يعيد تشغيل المهمة الأصلية. يجب أن
        تكون المهمة البديلة معلّقة، مرتبطة بقرار retry_authorized، وأن
        تكون كل تبعياتها مكتملة. يُمرر السياق المستعاد صراحة من المستدعي.
        """
        if not isinstance(replacement_task_id, str) or not replacement_task_id.strip():
            raise OrgError("replacement_task_id مطلوب")
        row = self.org_store.task_get(replacement_task_id)
        if row is None or row.get("mission_id") != ctx.mission.id:
            raise OrgError("مهمة إعادة المحاولة غير موجودة ضمن المهمة الحالية")
        if row.get("state") != "pending":
            raise OrgError("مهمة إعادة المحاولة ليست معلّقة")

        params = json.loads(row.get("params") or "{}")
        source_task_id = str(params.get("operator_retry_of") or "")
        if not source_task_id:
            raise OrgError("المهمة ليست إعادة محاولة مصرحًا بها من المشغّل")
        decisions = [
            decision for decision in self.org_store.task_reconciliations_for(
                ctx.mission.id)
            if decision.get("action") == "retry_authorized"
            and decision.get("replacement_task_id") == replacement_task_id
            and decision.get("task_id") == source_task_id
        ]
        if len(decisions) != 1:
            raise OrgError("لا يوجد قرار مشغّل وحيد يجيز إعادة هذه المهمة")
        source = self.org_store.task_get(source_task_id)
        if source is None or source.get("mission_id") != ctx.mission.id:
            raise OrgError("المهمة الأصلية لقرار إعادة المحاولة غير موجودة")

        deps = json.loads(row.get("deps") or "[]")
        for dependency_id in deps:
            dependency = self.org_store.task_get(str(dependency_id))
            if dependency is None or dependency.get("state") != "done":
                raise OrgError(
                    f"تبعية إعادة المحاولة لم تكتمل بنجاح: {dependency_id}")

        # بوابات المجلس والتحقق لها مسارات خاصة؛ لا نمررها إلى منفذ الأقسام.
        supported_departments = {
            "executive", "repo_intel", "development", "security", "qa", "release"
        }
        if row.get("dept") not in supported_departments:
            raise OrgError(
                "إعادة محاولة هذه البوابة تتطلب مسار استئناف مخصصًا للمهمة")

        spec = TaskSpec(
            mission_id=str(row["mission_id"]), dept=str(row["dept"]),
            kind=str(row["kind"]), description=str(row["description"]),
            deps=[str(dep) for dep in deps], params=params,
            id=str(row["id"]),
        )
        self.org_store.audit(
            "task.operator_retry_dispatched", replacement_task_id,
            {"source_task_id": source_task_id,
             "decision_id": decisions[0].get("id", "")},
        )
        return self._execute_task(spec, ctx)

    def _checkpoint_context(self, ctx: MissionContext) -> None:
        """Persist context after a completed task; never changes execution state."""
        if not ctx.mission.repo_path:
            return
        repo_root = Path(ctx.mission.repo_path)
        if not repo_root.is_dir():
            # Let the responsible repository-intelligence task fail and record its
            # durable failed attempt; there is no trustworthy source to fingerprint.
            return
        latest = self.org_store.mission_get(ctx.mission.id)
        if latest is None:
            raise OrgError("المهمة اختفت قبل حفظ سياقها")
        ctx.mission = latest
        save_mission_context_snapshot(self.org_store, ctx, self.state_root)

    def restore_context_for_resume(
            self, mission_id: str,
            expected_repo_root: str | Path | None = None) -> MissionContext:
        """Restore a context only after the read-only task-graph preflight passes.

        This method is a read-only restore/preflight boundary; it never dispatches
        work. The explicit resume_mission entry point owns continuation.
        """
        assessment = assess_mission_resume(self.org_store, mission_id)
        if not assessment.ready_for_explicit_resume:
            reasons = list(assessment.blocking_reasons)
            reasons.extend(assessment.dependency_violations)
            raise OrgError(
                "المهمة غير جاهزة للاستئناف: " + "; ".join(reasons))
        context = restore_mission_context(
            self.org_store, mission_id, self.state_root,
            expected_repo_root=expected_repo_root)
        current_mission = self.org_store.mission_get(mission_id)
        if current_mission is None:
            raise OrgError("المهمة اختفت أثناء استعادة السياق")
        context.mission = current_mission
        self.org_store.audit(
            "mission.context_restored", mission_id,
            {"snapshot_id": (self.org_store.mission_context_snapshot_get(
                mission_id) or {}).get("id", ""),
             "execution_started": False},
        )
        return context

    def _load_persisted_plan(self, mission_id: str) -> ExecutionPlan:
        """Rebuild the exact persisted DAG; never regenerate task identities."""
        plan = ExecutionPlan(mission_id=mission_id)
        rows = self.org_store.tasks_for_mission(mission_id)
        if not rows:
            raise OrgError("لا يوجد رسم مهام محفوظ لاستئنافه")
        for row in rows:
            try:
                deps = json.loads(row.get("deps") or "[]")
                params = json.loads(row.get("params") or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise OrgError(f"بيانات مهمة تالفة: {row.get('id', '')}") from exc
            if not isinstance(deps, list) or not isinstance(params, dict):
                raise OrgError(f"عقد مهمة غير صالح: {row.get('id', '')}")
            plan.tasks.append(TaskSpec(
                mission_id=str(row["mission_id"]),
                dept=str(row["dept"]),
                kind=str(row["kind"]),
                description=str(row["description"]),
                deps=[str(dep) for dep in deps],
                params=params,
                id=str(row["id"]),
            ))
        plan.validate()
        return plan

    @staticmethod
    def _task_result_payload(row: dict[str, Any]) -> dict[str, Any]:
        try:
            result = json.loads(row.get("result") or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise OrgError(f"نتيجة المهمة تالفة: {row.get('id', '')}") from exc
        if not isinstance(result, dict):
            raise OrgError(f"نتيجة المهمة ليست كائنًا: {row.get('id', '')}")
        return result

    def _resume_review_gate(self, plan: ExecutionPlan,
                            ctx: MissionContext) -> bool:
        """Continue the review/revision loop from its durable gate record."""
        while True:
            development_task = max(
                (task for task in plan.tasks if task.dept == "development"),
                key=lambda task: int(task.params.get("revision", 0)),
            )
            matching_reviews = [
                task for task in plan.tasks
                if task.dept == "code_review"
                and development_task.id in task.deps
            ]
            if len(matching_reviews) > 1:
                raise OrgError(
                    "أكثر من مهمة مراجعة مرتبطة بنسخة التطوير الحالية؛ الاستئناف مرفوض")
            review_task = matching_reviews[0] if matching_reviews else None
            if review_task is None:
                existing_rounds = [
                    int(task.params.get("round", 1))
                    for task in plan.tasks if task.dept == "code_review"
                ]
                self._queue_review_round(
                    plan, development_task, max(existing_rounds, default=1) + 1)
                self._checkpoint_context(ctx)
                review_task = plan.tasks[-1]

            row = self.org_store.task_get(review_task.id)
            if row is None:
                raise OrgError("سجل مهمة المراجعة اختفى أثناء الاستئناف")
            if row.get("state") == "pending":
                approved = self._run_review_gate(plan, ctx)
            elif row.get("state") == "done":
                result = self._task_result_payload(row)
                verdict = result.get("verdict")
                if (verdict not in {"approve", "request_changes"}
                        or result.get("development_task_id") != development_task.id):
                    raise OrgError(
                        "نتيجة المراجعة المكتملة لا تطابق نسخة التطوير الحالية")
                approved = verdict == "approve"
            else:
                raise OrgError(
                    f"حالة مهمة المراجعة غير قابلة للاستئناف: {row.get('state')}")

            if approved:
                return True

            stored = self.org_store.mission_get(ctx.mission.id)
            if stored is None:
                raise OrgError("المهمة اختفت بعد رفض المراجعة")
            next_revision = stored.revision_loops + 1
            self._bump_revision_loops(ctx.mission)
            if next_revision > self.max_revision_loops:
                self._fail(ctx.mission, "تجاوز سقف دورات المراجعة أثناء الاستئناف")
                return False

            self._advance_phase(ctx.mission, "D_REVIEW", "C_DEVELOP")
            self._queue_development_revision(
                plan, development_task, next_revision)
            self._checkpoint_context(ctx)
            self._run_wave(plan, ctx, phase="C_DEVELOP", dept="development")
            self._advance_phase(ctx.mission, "C_DEVELOP", "D_REVIEW")

    def resume_mission(
            self, mission_id: str, *, actor: str, reason: str,
            expected_repo_root: str | Path | None = None) -> Mission:
        """Explicitly continue a preflighted mission from its durable phase.

        This is an operator/caller action, not a background retry. It restores
        and validates the checkpoint first, rebuilds the persisted DAG without
        changing task IDs, skips completed tasks, and uses the existing durable
        claim paths for pending work. Review and verification remain specialized
        gates. A running/failed/skipped task or any drift blocks this method
        before execution.
        """
        if not isinstance(actor, str) or not actor.strip():
            raise OrgError("هوية المشغّل مطلوبة للاستئناف الصريح")
        if not isinstance(reason, str) or not reason.strip():
            raise OrgError("سبب الاستئناف مطلوب للتدقيق")
        ctx = self.restore_context_for_resume(
            mission_id, expected_repo_root=expected_repo_root)
        plan = self._load_persisted_plan(mission_id)
        mission = self.org_store.mission_get(mission_id)
        if mission is None:
            raise OrgError(f"مهمة غير موجودة: {mission_id}")
        self.org_store.audit("mission.resume_started", mission_id, {
            "actor": actor.strip(),
            "reason": reason.strip(),
            "phase": mission.phase,
            "pending_task_ids": [
                row["id"] for row in self.org_store.tasks_for_mission(mission_id)
                if row.get("state") == "pending"
            ],
            "execution_explicit": True,
        }, actor=actor.strip())
        try:
            while True:
                phase = self._current_phase(mission)
                if phase == "A_REQUIREMENTS":
                    self._run_wave(plan, ctx, phase=phase, dept="executive")
                    self._advance_phase(mission, phase, "B_INTEL")
                elif phase == "B_INTEL":
                    self._run_wave(plan, ctx, phase=phase, dept="repo_intel")
                    self._advance_phase(mission, phase, "C_DEVELOP")
                elif phase == "C_DEVELOP":
                    self._run_wave(plan, ctx, phase=phase, dept="development")
                    self._advance_phase(mission, phase, "D_REVIEW")
                elif phase == "D_REVIEW":
                    if not self._resume_review_gate(plan, ctx):
                        return self._final(mission, ctx, failed=True)
                    self._advance_phase(mission, phase, "E_TESTING")
                elif phase == "E_TESTING":
                    self._run_wave(plan, ctx, phase=phase, dept="qa")
                    self._run_wave(plan, ctx, phase=phase, dept="security")
                    self._advance_phase(mission, phase, "F_VERIFICATION")
                elif phase == "F_VERIFICATION":
                    verify_task = next(
                        (task for task in plan.tasks
                         if task.dept == "verification"), None)
                    if verify_task is None:
                        raise OrgError("مهمة التحقق غير موجودة في الرسم المحفوظ")
                    verify_row = self.org_store.task_get(verify_task.id)
                    if verify_row is None:
                        raise OrgError("سجل مهمة التحقق اختفى")
                    if verify_row.get("state") == "pending":
                        verified = self._run_verification_gate(
                            mission, plan, ctx)
                    elif verify_row.get("state") == "done":
                        result = self._task_result_payload(verify_row)
                        verified = (
                            isinstance(result.get("verified"), int)
                            and isinstance(result.get("rejected"), int)
                            and isinstance(result.get("reproduced"), bool)
                            and result["rejected"] == 0
                        )
                    else:
                        raise OrgError(
                            "حالة بوابة التحقق لا تسمح بالاستئناف")
                    if not verified:
                        self._fail(mission, "بوابة التحقق رفضت الأدلة أثناء الاستئناف")
                        return self._final(mission, ctx, failed=True)
                    self._advance_phase(mission, phase, "G_RELEASE")
                elif phase == "G_RELEASE":
                    self._run_wave(plan, ctx, phase=phase, dept="release")
                    return self._final(mission, ctx, failed=False)
                else:
                    raise OrgError(f"طور استئناف غير مدعوم: {phase}")
        except (DepartmentError, OrgError, PlanError, ValueError) as exc:
            self._fail(mission, f"فشل الاستئناف: {type(exc).__name__}: {exc}")
            return self._final(mission, ctx, failed=True, error=str(exc))
        finally:
            # Restored worktrees are non-owning; cleanup must never remove
            # the immutable checkpoint copy.
            if ctx.worktree is not None and getattr(ctx.worktree, "_owned", False):
                ctx.worktree.cleanup()

    def _persist_claims(self, ctx: MissionContext) -> None:
        """تخزين ادعاءات جديدة فقط — لا تكرار للادعاء المخزن."""
        stored = {c.statement for c in self.org_store.claims_for(ctx.mission.id)}
        for claim in ctx.claims:
            if claim.statement not in stored:
                self.org_store.add_claim(claim)
                stored.add(claim.statement)

    @staticmethod
    def _summarize(out: Any) -> str:
        """ملخص حتمي لناتج قسم — للتقرير واللوحة."""
        if isinstance(out, dict):
            keys = ",".join(sorted(out))[:120]
            status = out.get("status", "?")
            return f"status={status} keys={keys}"
        return type(out).__name__

    # ── البوابات ──────────────────────────────────────────────────────────

    def _queue_review_round(
            self, plan: ExecutionPlan, development_task: TaskSpec,
            round_number: int) -> TaskSpec:
        """إنشاء سجل مراجعة مستقل لكل نسخة تطوير؛ لا إعادة فتح مهمة سابقة."""
        if round_number < 2:
            raise OrgError("جولة المراجعة الإضافية يجب أن تبدأ من الجولة الثانية")
        spec = plan.add(
            "code_review", "council",
            f"مراجعة مستقلة — round {round_number} بعد {development_task.id}",
            deps=[development_task.id],
            params={
                "round": round_number,
                "reviews_development_task_id": development_task.id,
            },
        )
        self.org_store.add_task(spec)
        self.org_store.audit(
            "task.review_round_queued", spec.id,
            {
                "round": round_number,
                "reviews_development_task_id": development_task.id,
            },
        )
        return spec

    def _run_review_gate(self, plan: ExecutionPlan,
                         ctx: MissionContext) -> bool:
        """بوابة مراجعة ذات مطالبة دائمة مستقلة مرتبطة بنسخة التطوير الحالية."""
        development_task = max(
            (task for task in plan.tasks if task.dept == "development"),
            key=lambda task: int(task.params.get("revision", 0)),
        )
        review_task = next(
            (
                task for task in reversed(plan.tasks)
                if task.dept == "code_review"
                and development_task.id in task.deps
                and (self.org_store.task_get(task.id) or {}).get("state")
                == "pending"
            ),
            None,
        )
        if review_task is None:
            raise OrgError(
                "لا توجد مهمة مراجعة معلّقة مرتبطة بنسخة التطوير الحالية")
        claim = self.org_store.claim_task(
            review_task.id, worker_id="nexus-orchestrator:code_review")
        if claim is None:
            raise OrgError(f"مهمة المراجعة غير متاحة للمطالبة: {review_task.id}")
        lease_token = str(claim["lease_token"])
        try:
            decision, reviews = self.depts.council.review_with_debate(
                ctx.mission.id, review_task.id,
                dev_role="dev:backend", diff_text=ctx.diff_text,
                notes=ctx.dev_notes)
            ctx.council = decision
            for review in reviews:
                for issue in review.issues:
                    sev = str(issue.get("severity", "low"))
                    if sev not in ("critical", "high", "medium", "low", "info"):
                        sev = "low"
                    self.org_store.add_finding(
                        Finding(mission_id=ctx.mission.id, source="review",
                                category=f"review:{review.lens}",
                                severity=sev,
                                description=str(issue.get("message", "")),
                                file=str(issue.get("file", "")),
                                line=int(issue.get("line", 0) or 0)))
            result = {
                "verdict": decision.verdict,
                "mean": decision.mean_score,
                "rounds": decision.rounds,
                "development_task_id": development_task.id,
            }
            self.org_store.audit("gate.review", ctx.mission.id, result)
            self.org_store.finish_claimed_task(
                review_task.id, lease_token, result)
            self._checkpoint_context(ctx)
            return decision.verdict == "approve"
        except Exception as exc:  # noqa: BLE001 — المطالبة تُنهى أو تفشل صراحة
            self.org_store.fail_claimed_task(
                review_task.id, lease_token,
                f"{type(exc).__name__}: {exc}")
            raise

    def _run_verification_gate(self, mission: Mission, plan: ExecutionPlan,
                               ctx: MissionContext) -> bool:
        """بوابة تحقق بمطالبة دائمة؛ الرفض نتيجة مكتملة لا إعادة تشغيل تلقائية."""
        verify_task = next(
            (task for task in plan.tasks if task.dept == "verification"), None)
        if verify_task is None:
            raise OrgError("مهمة التحقق غير موجودة في خطة المهمة")
        claim = self.org_store.claim_task(
            verify_task.id, worker_id="nexus-orchestrator:verification")
        if claim is None:
            raise OrgError(f"مهمة التحقق غير متاحة للمطالبة: {verify_task.id}")
        lease_token = str(claim["lease_token"])
        try:
            test_target = (ctx.affected.get("test_files") or [""])[0]
            report = self.verification.verify_mission(
                mission, ctx.claims,
                self.org_store.evidence_for(mission.id),
                ctx.worktree, test_target=test_target)
            result = {
                "verified": report.verified,
                "rejected": report.rejected,
                "reproduced": report.reproduced_fix,
            }
            self.org_store.audit(
                "gate.verification", mission.id, report.to_dict())
            self.org_store.finish_claimed_task(
                verify_task.id, lease_token, result)
            self._checkpoint_context(ctx)
            return not report.rejected
        except Exception as exc:  # noqa: BLE001 — لا نترك بوابة بلا نتيجة دائمة
            self.org_store.fail_claimed_task(
                verify_task.id, lease_token,
                f"{type(exc).__name__}: {exc}")
            raise

    # ── أدوات الحالة ──────────────────────────────────────────────────────

    def _advance_phase(self, mission: Mission, from_phase: str,
                       to_phase: str) -> None:
        """انتقال طور عبر المتجر — آلة الحالات هي الحارس الوحيد.

        القراءة حديثة من المتجر ثم نسخة بطور جديد — لا كتابة من كائن
        محلّي قديم يصفّر ما ثبّته الأقسام (معايير القبول ومساراتها).
        """
        current = self._current_phase(mission)
        if current != from_phase:
            raise OrgError(
                f"طور فعلي {current} لا يطابق منبوذَ البوابة {from_phase}")
        stored = self.org_store.mission_get(mission.id)
        assert stored is not None
        self.org_store.mission_update(stored.with_phase(to_phase))

    def _bump_revision_loops(self, mission: Mission) -> None:
        """عدّاد دورات المراجعة في سجل المهمة — شفافية الدورة معلنة."""
        stored = self.org_store.mission_get(mission.id)
        assert stored is not None
        from dataclasses import replace
        self.org_store.mission_update(replace(
            stored, revision_loops=stored.revision_loops + 1))

    def _current_phase(self, mission: Mission) -> str:
        stored = self.org_store.mission_get(mission.id)
        assert stored is not None, "المهمة مخزونة قبل التنفيذ"
        return stored.phase

    def _store_criteria(self, mission: Mission, out: dict[str, Any]) -> None:
        """تثبيت معايير القبول المستخرجة في سجل المهمة."""
        stored = self.org_store.mission_get(mission.id)
        assert stored is not None
        updated = Mission(
            title=stored.title, objective=stored.objective,
            repo_path=stored.repo_path,
            acceptance_criteria=out.get("acceptance_criteria", []),
            constraints=out.get("constraints", []),
            ambiguities=out.get("ambiguities", []),
            phase=stored.phase, status=stored.status, id=stored.id,
            branch=stored.branch, patch_path=stored.patch_path,
            report_path=stored.report_path, ticket_ids=stored.ticket_ids,
            revision_loops=stored.revision_loops)
        self.org_store.mission_update(updated)

    def _fail(self, mission: Mission, reason: str) -> None:
        """فشل صريح — الطور FAILED والحالة failed والسبب مدقَّق."""
        stored = self.org_store.mission_get(mission.id)
        if stored is None:
            return
        phase = stored.phase
        if "FAILED" in ALLOWED_PHASE_TRANSITIONS.get(phase, frozenset()):
            stored = self.org_store.mission_update(stored.with_phase("FAILED"))
        self.org_store.mission_update(
            Mission(title=stored.title, objective=stored.objective,
                    repo_path=stored.repo_path, status="failed",
                    phase=stored.phase, id=stored.id,
                    acceptance_criteria=stored.acceptance_criteria,
                    constraints=stored.constraints,
                    ambiguities=stored.ambiguities, branch=stored.branch,
                    patch_path=stored.patch_path,
                    report_path=stored.report_path,
                    ticket_ids=stored.ticket_ids,
                    revision_loops=stored.revision_loops))
        self.org_store.audit("mission.failed", mission.id, {"reason": reason})

    def _final(self, mission: Mission, ctx: MissionContext,
               failed: bool, error: str = "") -> Mission:
        stored = self.org_store.mission_get(mission.id)
        assert stored is not None
        status = "failed" if failed else "done"
        branch = stored.branch or (f"org/{stored.id}" if not failed else "")
        from src.org.contracts import Claim
        final = Mission(
            title=stored.title, objective=stored.objective,
            repo_path=stored.repo_path,
            acceptance_criteria=stored.acceptance_criteria,
            constraints=stored.constraints, ambiguities=stored.ambiguities,
            phase=stored.phase, status=status, id=stored.id, branch=branch,
            patch_path=stored.patch_path, report_path=stored.report_path,
            ticket_ids=stored.ticket_ids,
            revision_loops=stored.revision_loops)
        stored = self.org_store.mission_update(final)
        self.org_store.audit("mission.finished", stored.id,
                             {"status": status, "error": error[:200],
                              "usage": dict(ctx.usage)})
        return stored
