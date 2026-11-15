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

import time
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
                 max_revision_loops: int = 2) -> None:
        self.org_store = org_store
        self.ops_store = ops_store
        self.depts = Departments(pool or ProviderPool(), org_store,
                                 ops_store, outdir)
        self.verification = VerificationEngine(
            self.depts.runtime, org_store, self.depts.runner)
        self.max_workers = max_workers
        self.max_revision_loops = max_revision_loops

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
            while True:
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
        """تنفيذ مهام طور واحد — موازٍ داخل الموجة، فشل قسم = رفع."""
        wave = [t for t in plan.tasks if t.dept == dept]
        if not wave:
            return
        if len(wave) == 1:
            self._execute_task(wave[0], ctx)
            return
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._execute_task, t, ctx): t
                       for t in wave}
            for future in as_completed(futures):
                future.result()

    def _execute_task(self, spec: TaskSpec, ctx: MissionContext) -> TaskResult:
        """تنفيذ مهمة قسم واحدة — تسجيل حالة ونتيجة واستهلاك في المتجر."""
        self.org_store.task_set_state(spec.id, "running")
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
                output={"summary": summary}, attempts=1,
                duration_ms=round((time.time() - t0) * 1000, 2))
            self.org_store.task_set_state(spec.id, "done",
                                          result=result.output, attempts=1)
            return result
        except Exception as exc:  # noqa: BLE001 — الفشل يُسجَّل ثم يُرفع
            self.org_store.task_set_state(
                spec.id, "failed", error=f"{type(exc).__name__}: {exc}",
                attempts=1)
            raise

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

    def _run_review_gate(self, plan: ExecutionPlan,
                         ctx: MissionContext) -> bool:
        """بوابة المراجعة — مجلس مستقل على الرقعة، أسباب موثقة."""
        review_task = next(
            (t for t in plan.tasks if t.dept == "code_review"), None)
        decision, reviews = self.depts.council.review_with_debate(
            ctx.mission.id, review_task.id if review_task else "",
            dev_role="dev:backend", diff_text=ctx.diff_text,
            notes=ctx.dev_notes)
        if review_task is not None:
            self.org_store.task_set_state(review_task.id, "done",
                                          result={"verdict": decision.verdict,
                                                  "mean": decision.mean_score})
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
        self.org_store.audit("gate.review", ctx.mission.id,
                             {"verdict": decision.verdict,
                              "mean": decision.mean_score,
                              "rounds": decision.rounds})
        return decision.verdict == "approve"

    def _run_verification_gate(self, mission: Mission, plan: ExecutionPlan,
                               ctx: MissionContext) -> bool:
        """بوابة التحقق — حسم كل ادعاء وإعادة إنتاج الإصلاح."""
        test_target = (ctx.affected.get("test_files") or [""])[0]
        report = self.verification.verify_mission(
            mission, ctx.claims,
            self.org_store.evidence_for(mission.id),
            ctx.worktree, test_target=test_target)
        verify_task = next(
            (t for t in plan.tasks if t.dept == "verification"), None)
        if verify_task is not None:
            self.org_store.task_set_state(
                verify_task.id, "done",
                result={"verified": report.verified,
                        "rejected": report.rejected,
                        "reproduced": report.reproduced_fix})
        self.org_store.audit("gate.verification", mission.id, report.to_dict())
        return not report.rejected

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
