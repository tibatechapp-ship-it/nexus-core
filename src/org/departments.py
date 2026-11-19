"""الأقسام الثمانية — العاملون الحقيقيون لكل قسم بعقد ونواتج معلنة.

القواعد المعلنة:

* **كل قسم عامل واحد بمدخل مُعلن وناتج قاموسي مُعلن** — لا قيم
  اختيارية صامتة: الناتج يحمل دائمًا ``status`` وملخص ما جرى.
* **المستودع الأصلي للقراءة فقط**: كل كتابة تحدث في ``Worktree`` نسخة
  عمل مؤقتة — الرقعة تُبنى بفرق نصي بين الأصل والنسخة، ولا يُلمس الأصل.
* **كل قسم يولّد ادعاءات وأدلة**: ادعاء بلا دليل يبقى ``unverified``
  ويُرفض في قسم التحقق — لا قسم يمنح نفسه التصديق.
* **الإصدار لا يدمج أبدًا ذاتيًا**: قسم الإصدار يفتح تذكرة تشغيلية
  بـ``publish_allowed=False`` ويطلب موافقة بشرية — القرار للبشر فقط.
* **الاستهلاك يُجمَّع**: كل قسم يعيد توكناته وكلفته ليجمعها المُنسّق.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import difflib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.org.agents import AgentOutcome, AgentRuntime, AgentSpec, Tool, ToolRegistry
from src.coder.engine import run_engine
from src.coder.org_connector import OrgRuntimeConnector
from src.org.contracts import (
    Approval,
    Claim,
    DEV_KINDS,
    Evidence,
    Finding,
    Mission,
    new_id,
)
from src.org.providers import ProviderPool
from src.org.repo_intel import RepoIntelligence, RepoMap
from src.org.review import CouncilDecision, ReviewCouncil
from src.org.sandbox import RunResult, WorkspaceRunner, Worktree
from src.org.security import InjectionGuard, security_report
from src.org.store import OrgStore
from src.ops.store import OpsStore

__all__ = [
    "DepartmentError",
    "Departments",
    "MissionContext",
    "build_tool_registry",
]


class DepartmentError(RuntimeError):
    """فشل قسم صريح — يُسجَّل ويُرفع لا يُكتم."""


@dataclass
class MissionContext:
    """حقيبة المهمة المشتركة — ما تجمعه الأقسام من بعضها بترتيب معلن.

    العقد: كل حقل يكتبه قسم واحد معلن في التعليق، ويقرأه الأقسام
    اللاحقة فقط — لا كتابة متوازية على نفس الحقل.
    """

    mission: Mission
    worktree: Worktree | None = None            # يكتبه: ذكاء المستودع
    repo_map: RepoMap | None = None             # يكتبه: ذكاء المستودع
    intel_summary: dict[str, Any] = field(default_factory=dict)   # ذكاء المستودع
    affected: dict[str, Any] = field(default_factory=dict)        # ذكاء المستودع
    originals: dict[str, str] = field(default_factory=dict)       # ذكاء المستودع
    diff_text: str = ""                          # يكتبه: التطوير
    changed_files: list[str] = field(default_factory=list)        # التطوير
    dev_notes: str = ""                          # التطوير
    dev_risks: list[dict[str, Any]] = field(default_factory=list)  # التطوير
    security_report: dict[str, Any] = field(default_factory=dict)  # الأمن
    baseline_tests: dict[str, Any] = field(default_factory=dict)   # الجودة
    patched_tests: dict[str, Any] = field(default_factory=dict)    # الجودة
    council: CouncilDecision | None = None       # يكتبه: المراجعة
    claims: list[Claim] = field(default_factory=list)              # كل الأقسام
    pr_text: dict[str, Any] = field(default_factory=dict)          # الإصدار
    usage: dict[str, int | float] = field(default_factory=dict)    # المُنسّق
    execution_policy: dict[str, Any] = field(default_factory=dict)  # سياسة ثابتة للاستئناف

    def add_usage(self, outcome: AgentOutcome) -> None:
        """تجميع استهلاك وكيل واحد في حقيبة المهمة."""
        self.usage["tokens_in"] = int(self.usage.get("tokens_in", 0)) \
            + outcome.tokens_in
        self.usage["tokens_out"] = int(self.usage.get("tokens_out", 0)) \
            + outcome.tokens_out
        self.usage["cost_usd_milli"] = round(
            float(self.usage.get("cost_usd_milli", 0.0)) + outcome.cost_usd * 1000,
            4)


def build_tool_registry(source_root: Path, guard: InjectionGuard) -> ToolRegistry:
    """أدوات معلنة بصلاحيات — قراءة مستودع، مسح أمني، تحييد محتوى."""
    registry = ToolRegistry()

    def read_repo_file(rel_path: str) -> dict[str, Any]:
        """قراءة ملف من المستودع الأصلي — قراءة فقط لا كتابة."""
        target = (source_root / rel_path).resolve()
        if source_root.resolve() not in target.parents:
            raise PermissionError(f"مسار خارج المستودع مرفوض: {rel_path}")
        return {"path": rel_path,
                "content": target.read_text(encoding="utf-8", errors="ignore")}

    def scan_target(rel_path: str) -> dict[str, Any]:
        """مسح أمني ساكن لملف — أسرار وتهديد وحقن."""
        text = (source_root / rel_path).read_text(encoding="utf-8",
                                                  errors="ignore")
        from src.org.security import scan_text_for_secrets, threat_model_scan
        secrets = scan_text_for_secrets(text, rel_path)
        threats = threat_model_scan(text, rel_path)
        injections = guard.scan(text, rel_path)
        return {"path": rel_path, "secrets": len(secrets),
                "threat_hits": len(threats), "injections": len(injections)}

    registry.register(Tool("read_repo", "قراءة ملف مستودع (قراءة فقط)",
                           read_repo_file))
    registry.register(Tool("security_scan", "مسح أمني ساكن لملف", scan_target))
    return registry


# ── 1: المتطلبات (التنفيذي) ───────────────────────────────────────────────


class RequirementsOffice:
    """قسم المتطلبات — تحليل هدف، معايير قبول، غموض، قيود."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    def run(self, ctx: MissionContext) -> dict[str, Any]:
        spec = AgentSpec(role="requirements:analyst", dept="executive",
                         mission_id=ctx.mission.id, max_retries=1)
        prompt = (
            f"OBJECTIVE: {ctx.mission.objective}\n"
            f"TITLE: {ctx.mission.title}\n"
            "استخرج: acceptance_criteria (قائمة قابلة للقياس)، constraints، "
            "ambiguities (ما يحتاج تثبيتًا بشريًا)."
        )
        outcome = self.runtime.ask_json(spec, prompt)
        ctx.add_usage(outcome)
        if not outcome.success:
            raise DepartmentError(f"فشل تحليل المتطلبات: {outcome.error}")
        criteria = [str(x) for x in outcome.data.get("acceptance_criteria", [])]
        constraints = [str(x) for x in outcome.data.get("constraints", [])]
        ambiguities = [str(x) for x in outcome.data.get("ambiguities", [])]
        claim = Claim(mission_id=ctx.mission.id, agent_role=spec.role,
                      statement=f"المعايير المستخرجة تغطي الهدف: "
                                f"{len(criteria)} معيارًا",
                      claim_kind="observation",
                      id=new_id("org-c", ctx.mission.id, spec.role,
                                f"المعايير المستخرجة تغطي الهدف: "
                                f"{len(criteria)} معيارًا"))
        ctx.claims.append(claim)
        self.runtime.store.add_evidence(Evidence(
            mission_id=ctx.mission.id, kind="log",
            detail={"criteria": criteria},
            captured_by=spec.role, ok=True, claim_id=claim.id))
        return {"status": "ok", "acceptance_criteria": criteria,
                "constraints": constraints, "ambiguities": ambiguities,
                "claim": claim}


# ── 2: ذكاء المستودع ──────────────────────────────────────────────────────


class RepoIntelDept:
    """قسم ذكاء المستودع — مسح تزايدي، خريطة، تأثير، ملخص تخطيطي."""

    def __init__(self, runtime: AgentRuntime, guard: InjectionGuard) -> None:
        self.runtime = runtime
        self.guard = guard

    def run(self, ctx: MissionContext) -> dict[str, Any]:
        if not ctx.mission.repo_path:
            raise DepartmentError("المهمة بلا مستودع — ذكاء المستودع مرفوض")
        root = Path(ctx.mission.repo_path)
        if not root.is_dir():
            raise DepartmentError(f"مجلد المستودع غير موجود: {root}")
        engine = RepoIntelligence(root)
        repo_map = engine.scan(incremental=True)
        intel = engine.summary_for_planning(repo_map)
        # أهداف التغيير المرشحة: من وسم المهمة أو ملفات الاختبار والمصادر
        targets = self._propose_targets(ctx.mission.objective, repo_map)
        affected = engine.affected_files(targets)
        # نسخة العمل: ملفات التأثير + اختباراتها — الأصل يبقى للقراءة
        files = list(dict.fromkeys(
            affected["direct"] + affected["transitive"] + affected["test_files"]))
        ctx.worktree = Worktree.from_source(root, files=files) if files \
            else Worktree.from_source(root, whole=True)
        for rel in files:
            src_file = root / rel
            if src_file.is_file():
                ctx.originals[rel] = src_file.read_text(encoding="utf-8",
                                                        errors="ignore")
        # ملخص النموذج على محتوى محيَّد — الحقن لا يصل للنموذج
        spec = AgentSpec(role="repo_intel:analyzer", dept="repo_intel",
                         mission_id=ctx.mission.id, max_retries=1)
        files_block = "\n".join(f"file: {m.rel_path}" for m in repo_map.modules[:12])
        neutral_files = self.guard.neutralize(files_block)
        prompt = (f"لخّص المعمارية من قائمة الوحدات (محتوى مُحيَّد):\n"
                  f"{neutral_files}\nOBJECTIVE: {ctx.mission.objective}")
        outcome = self.runtime.ask_json(spec, prompt)
        ctx.add_usage(outcome)
        ctx.repo_map = repo_map
        ctx.intel_summary = intel
        ctx.affected = affected
        statement = (f"خريطة المستودع: {len(repo_map.modules)} وحدة، "
                     f"{len(repo_map.import_edges())} حافة استيراد")
        claim = Claim(mission_id=ctx.mission.id, agent_role="repo_intel:analyzer",
                      statement=statement, claim_kind="observation",
                      id=new_id("org-c", ctx.mission.id, "repo_intel:analyzer",
                                statement))
        ctx.claims.append(claim)
        self.runtime.store.add_evidence(Evidence(
            mission_id=ctx.mission.id, kind="static_analysis",
            detail={"intel": intel},
            captured_by="repo_intel:analyzer", ok=True, claim_id=claim.id))
        return {"status": "ok", "intel": intel, "affected": affected,
                "targets": targets, "worktree_files": files, "claim": claim}

    @staticmethod
    def _propose_targets(objective: str, repo_map: RepoMap) -> list[str]:
        """ترشيح حتمي لأهداف التغيير — كلمات هدف تطابق أسماء وحدات."""
        words = [w.strip(".,:;!?()«»").lower() for w in objective.split()]
        targets: list[str] = []
        for m in repo_map.modules:
            stem = Path(m.rel_path).stem.lower()
            if stem in words or any(stem and stem in w for w in words):
                targets.append(m.rel_path)
        if not targets:
            # الترشيح الاحتياطي: ملفات مصدر غير اختبار مرتبة حتميًا
            targets = [m.rel_path for m in repo_map.modules
                       if m.rel_path.endswith(".py")
                       and "test" not in Path(m.rel_path).name][:2]
        return targets[:4]


# ── 3: التطوير ────────────────────────────────────────────────────────────


class DevelopmentDept:
    """قسم التطوير — يفوض التخطيط والتنفيذ والتحقق إلى Coder Engine."""

    def __init__(
        self,
        runtime: AgentRuntime,
        connector_factory: Callable[[AgentRuntime, str], Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.connector_factory = connector_factory

    @staticmethod
    def _function_hint(objective: str, target: str) -> str:
        """Backward-compatible deterministic hint for older department clients."""
        import re
        match = re.search(r"دالة\s*[`\"']?(\w+)", objective)
        if match:
            return match.group(1)
        for word in ("divide", "split", "parse", "validate", "login", "create"):
            if word in objective.lower():
                return word
        return Path(target).stem

    @staticmethod
    def _guard_hint(objective: str) -> str:
        """Backward-compatible guard description; never used as execution authority."""
        lowered = objective.lower()
        for keyword, hint in (
            ("صفر", "القسمة على صفر"), ("zero", "القسمة على صفر"),
            ("empty", "مدخلات فارغة"), ("فارغ", "مدخلات فارغة"),
            ("auth", "طلبات بلا تصريح"), ("negative", "قيم سالبة"),
        ):
            if keyword in lowered:
                return hint
        return "مدخلات غير صالحة"

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Run the async engine from this synchronous department API."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()

    def run(self, ctx: MissionContext, dev_kind: str = "backend") -> dict[str, Any]:
        if dev_kind not in DEV_KINDS:
            raise DepartmentError(f"نوع تطوير غير معلن: {dev_kind}")
        if ctx.worktree is None:
            raise DepartmentError("لا نسخة عمل — الذكاء يجب أن يسبق التطوير")
        repo_path = ctx.mission.repo_path
        if not repo_path or not Path(repo_path).is_dir():
            raise DepartmentError("محرك Coder يحتاج مسار مستودع صالحًا")
        targets = ctx.affected.get("direct") or list(ctx.originals)[:1]
        if not targets:
            raise DepartmentError("لا ملفات هدف محددة للتطوير")

        # Execution mode is a mission-level security decision. Never silently
        # fall back to the legacy process runner for an arbitrary repository.
        execution_policy = ctx.execution_policy
        execution_mode = execution_policy.get("execution_mode")
        container_image = execution_policy.get("container_image")
        container_enabled = execution_policy.get("container_enabled") is True
        approval_id = execution_policy.get("approval_id")
        approvals = self.org_store.approvals_for(ctx.mission.id)
        container_approved = any(
            item.id == approval_id
            and item.kind == "run_untrusted"
            and item.approved is True
            and bool(item.decided_by)
            and item.subject == container_image
            for item in approvals
        )
        if execution_mode == "process":
            if execution_policy.get("trusted_local") is not True:
                raise DepartmentError(
                    "process mode requires an explicit trusted_local mission policy"
                )
        elif execution_mode == "container":
            if not container_enabled or not container_approved:
                raise DepartmentError(
                    "container mode requires explicit enablement and human approval"
                )
            digest = (container_image.rsplit("@sha256:", 1)[-1]
                      if isinstance(container_image, str) and "@sha256:" in container_image
                      else "")
            if (len(digest) != 64
                    or any(ch not in "0123456789abcdefABCDEF" for ch in digest)):
                raise DepartmentError(
                    "container mode requires a valid immutable sha256 image digest"
                )
        else:
            raise DepartmentError(
                "execution policy missing: choose approved container mode or "
                "explicit trusted-local process mode"
            )

        engine_workdir = Path(tempfile.mkdtemp(prefix="nexus-coder-mission-"))
        connector = (
            self.connector_factory(self.runtime, ctx.mission.id)
            if self.connector_factory is not None else
            OrgRuntimeConnector(
                self.runtime, mission_id=ctx.mission.id,
                max_tokens=4000, max_retries=1, timeout_s=120.0,
            )
        )
        try:
            result = self._run_async(run_engine(
                ctx.mission.objective, connector, root=Path(repo_path),
                workdir=engine_workdir, max_iterations=3,
                council_mode="off", execution_mode=execution_mode,
                container_image=container_image,
                container_enabled=container_enabled,
                container_approved=container_approved,
                test_timeout=90,
            ))
            usage = connector.usage_total
            if any(usage.values()):
                ctx.add_usage(AgentOutcome(
                    spec_role=f"dev:{dev_kind}", success=bool(result.get("ok")),
                    tokens_in=int(usage["tokens_in"]),
                    tokens_out=int(usage["tokens_out"]),
                    cost_usd=usage["cost_usd"],
                    provider_used=";".join(sorted(connector.providers_used)),
                    model_used=";".join(sorted(connector.models_used)),
                ))
            if not result.get("ok"):
                raise DepartmentError(
                    "فشل Coder Engine: " + str(result.get("error", "unknown"))[:400]
                )
            plan = result.get("plan")
            if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
                raise DepartmentError("Coder Engine لم يُرجع RepairPlan قابلة للتطبيق")

            repo_root = Path(repo_path).resolve()
            allowed_paths = set(ctx.originals)
            for key in ("direct", "transitive", "test_files"):
                values = ctx.affected.get(key, [])
                if isinstance(values, list):
                    allowed_paths.update(str(value) for value in values)
            allowed_dirs = {str(Path(value).parent.as_posix()) for value in allowed_paths}
            for step in plan["steps"]:
                if not isinstance(step, dict):
                    raise DepartmentError("RepairPlan تحتوي خطوة غير صالحة")
                rel = step.get("file")
                if not isinstance(rel, str) or not rel:
                    raise DepartmentError("RepairPlan تحتوي مسارًا فارغًا")
                source = (repo_root / rel).resolve()
                if not source.is_relative_to(repo_root):
                    raise DepartmentError(f"مسار خارج المستودع مرفوض: {rel}")
                if step.get("action") in {"edit", "delete"} and rel not in allowed_paths:
                    raise DepartmentError(f"الملف خارج نطاق المهمة المعلن: {rel}")
                if step.get("action") == "create":
                    parent = Path(rel).parent.as_posix()
                    if parent not in allowed_dirs:
                        raise DepartmentError(f"إنشاء ملف خارج نطاق المهمة مرفوض: {rel}")
                if rel not in ctx.originals:
                    try:
                        ctx.originals[rel] = (
                            source.read_text(encoding="utf-8") if source.is_file() else ""
                        )
                    except (OSError, UnicodeError) as exc:
                        raise DepartmentError(f"تعذر قراءة خط أساس {rel}: {exc}") from exc

            try:
                applied = ctx.worktree.apply_repair_steps(plan["steps"])
            except (ValueError, OSError) as exc:
                raise DepartmentError(f"رفض تطبيق RepairPlan: {exc}") from exc
            if not applied:
                raise DepartmentError("RepairPlan لم تنتج تغييرات قابلة للتطبيق")

            changes: list[dict[str, str]] = []
            for step in plan["steps"]:
                rel = step["file"]
                content = "" if step["action"] == "delete" else ctx.worktree.read(rel)
                changes.append({"path": rel, "content": content})
            ctx.changed_files = sorted(set(applied))
            ctx.diff_text = self._build_diff(ctx, changes)
            ctx.dev_notes = str(plan.get("goal", ctx.mission.objective))
            ctx.dev_risks = [
                {"severity": step.get("risk", "low"),
                 "message": str(step.get("reason", ""))}
                for step in plan["steps"] if step.get("risk") in {"medium", "high"}
            ]
            statement = (
                f"نفّذ Coder Engine خطة إصلاح على {len(applied)} ملفًا "
                "داخل نسخة العمل بعد اجتياز بوابة الاختبارات"
            )
            claim = Claim(
                mission_id=ctx.mission.id, agent_role=f"dev:{dev_kind}",
                statement=statement, claim_kind="fix",
                id=new_id("org-c", ctx.mission.id, f"dev:{dev_kind}", statement),
            )
            ctx.claims.append(claim)
            self.runtime.store.add_evidence(Evidence(
                mission_id=ctx.mission.id, kind="diff",
                detail={"paths": applied, "diff_chars": len(ctx.diff_text),
                        "engine_iterations": result.get("iterations", 0),
                        "promotion": result.get("promotion", "pending")},
                captured_by=f"dev:{dev_kind}", ok=True, claim_id=claim.id,
            ))
            return {
                "status": "ok", "applied": applied,
                "diff_chars": len(ctx.diff_text), "engine": result, "claim": claim,
            }
        finally:
            shutil.rmtree(engine_workdir, ignore_errors=True)

    @staticmethod
    def _build_diff(ctx: MissionContext,
                    changes: list[dict[str, str]]) -> str:
        """فرق نصي موحّد بين الأصل ونسخة العمل — دليل قابل للتدقيق."""
        lines: list[str] = []
        by_path = {c["path"]: c.get("content", "") for c in changes}
        for path in sorted(set(list(by_path) + list(ctx.originals))):
            old = ctx.originals.get(path, "")
            new = by_path.get(path, ctx.worktree.read(path) if ctx.worktree else "")
            diff = difflib.unified_diff(
                old.splitlines(), new.splitlines(),
                fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="")
            lines.extend(diff)
        return "\n".join(lines)


class SecurityDept:
    """قسم الأمن — أسرار، تبعيات، حقن، نموذج تهديد على الرقعة والمتأثرات."""

    def __init__(self, runtime: AgentRuntime, guard: InjectionGuard) -> None:
        self.runtime = runtime
        self.guard = guard

    def run(self, ctx: MissionContext,
            requirements_text: str = "") -> dict[str, Any]:
        texts: dict[str, str] = {}
        if ctx.worktree is not None:
            for rel in ctx.changed_files:
                try:
                    texts[f"patch:{rel}"] = ctx.worktree.read(rel)
                except (ValueError, OSError):
                    continue
        for rel, original in sorted(ctx.originals.items()):
            if "requirements" in Path(rel).name:
                requirements_text = requirements_text or original
        report = security_report(requirements_text=requirements_text,
                                 texts=texts, guard=self.guard)
        ctx.security_report = report
        findings: list[Finding] = []
        for hit in report["secrets"]:
            findings.append(Finding(
                mission_id=ctx.mission.id, source="security", category="secret",
                severity="critical", description=f"سر مكتشف ({hit['kind']}) — نص منقّح",
                file=hit["file"], line=int(hit["line"])))
        for hit in report["threat_model"]:
            findings.append(Finding(
                mission_id=ctx.mission.id, source="security",
                category=f"threat:{hit['rule']}", severity=hit["severity"],
                description=hit["reason"], file=hit["file"], line=int(hit["line"])))
        for hit in report["injections"]:
            findings.append(Finding(
                mission_id=ctx.mission.id, source="security", category="injection",
                severity="high",
                description=f"إشارة حقن مطالبة: {hit['signal']}",
                file=hit["file"], line=int(hit["line"])))
        for hit in report["dependencies"]:
            findings.append(Finding(
                mission_id=ctx.mission.id, source="security",
                category="dependency", severity=hit["severity"],
                description=f"{hit['package']} {hit['cve']}: {hit['summary']}"))
        critical = [f for f in findings if f.severity in ("critical", "high")]
        statement = f"المسح الأمني: {report['counts']}"
        claim = Claim(mission_id=ctx.mission.id, agent_role="security:scanner",
                      statement=statement, claim_kind="observation",
                      id=new_id("org-c", ctx.mission.id, "security:scanner",
                                statement))
        ctx.claims.append(claim)
        self.runtime.store.add_evidence(Evidence(
            mission_id=ctx.mission.id, kind="scan",
            detail={"counts": report["counts"]},
            captured_by="security:scanner",
            ok=not critical, claim_id=claim.id))
        return {"status": "ok", "findings": findings, "report": report,
                "blocking_count": len(critical), "claim": claim}


# ── 5: الجودة ─────────────────────────────────────────────────────────────


class QADept:
    """قسم الجودة — أساس قبل الرقعة، اختبارات بعد الرقعة، وتحليل انحدار.

    كل تشغيل داخل ``WorkspaceRunner`` المعزول — حدود موارد ومهلة وبيئة
    مُنقّحة، والنتيجة تُخزَّن دليلًا كاملًا قابلًا لإعادة الإنتاج.
    """

    def __init__(self, runner: WorkspaceRunner,
                 store: OrgStore | None = None) -> None:
        self.runner = runner
        self.store = store

    def baseline(self, ctx: MissionContext) -> dict[str, Any]:
        """تشغيل أساس على الأصل — يعرف ما كان أخضر قبل التغيير."""
        if not ctx.mission.repo_path or not ctx.originals:
            ctx.baseline_tests = {"status": "skipped", "reason": "لا أساس معلن"}
            return ctx.baseline_tests
        base_wt = Worktree.from_source(Path(ctx.mission.repo_path),
                                       files=sorted(ctx.originals))
        try:
            targets = sorted(ctx.affected.get("test_files", [])) or None
            result = self._run_pytest(base_wt, target=targets[0] if targets else "")
            ctx.baseline_tests = self._pack(result, label="baseline")
            if self.store is not None:
                self.store.add_evidence(Evidence(
                    mission_id=ctx.mission.id, kind="test_result",
                    detail={**result.to_detail(), "label": "baseline"},
                    captured_by="qa:runner",
                    ok=result.returncode == 0 and not result.timed_out))
        finally:
            base_wt.cleanup()
        return ctx.baseline_tests

    def patched(self, ctx: MissionContext) -> dict[str, Any]:
        """تشغيل الاختبارات على الرقعة داخل نسخة العمل المعزولة."""
        if ctx.worktree is None:
            raise DepartmentError("لا نسخة عمل لتشغيل الاختبارات")
        targets = sorted(ctx.affected.get("test_files", []))
        result = self._run_pytest(ctx.worktree,
                                  target=targets[0] if targets else "")
        ctx.patched_tests = self._pack(result, label="patched")
        tests_ok = result.returncode == 0 and not result.timed_out
        statement = ("اختبارات الرقعة خضراء" if tests_ok
                     else f"اختبارات الرقعة حمراء ({result.returncode})")
        claim = Claim(
            mission_id=ctx.mission.id, agent_role="qa:runner",
            statement=statement, claim_kind="test_pass",
            id=new_id("org-c", ctx.mission.id, "qa:runner", statement))
        ctx.claims.append(claim)
        if self.store is not None:
            self.store.add_evidence(Evidence(
                mission_id=ctx.mission.id, kind="test_result",
                detail={**result.to_detail(), "label": "patched"},
                captured_by="qa:runner", ok=tests_ok,
                claim_id=claim.id))
        return ctx.patched_tests

    def _run_pytest(self, wt: Worktree, target: str = "") -> RunResult:
        """تشغيل pytest على نسخة العمل — مهلة قصيرة معلنة للاختبارات."""
        import shutil
        if shutil.which("python3") is None:
            return RunResult(command=["pytest-missing"], returncode=-2,
                             stdout="", stderr="python3 غير متوفر",
                             duration_ms=0.0)
        return self.runner.run_python_tests(wt.root, target=target)

    @staticmethod
    def _pack(result: RunResult, label: str) -> dict[str, Any]:
        return {
            "status": "ok" if result.returncode == 0 and not result.timed_out
            else "failed",
            "label": label,
            "detail": result.to_detail(),
        }


# ── 6: التحقق المستقل (يُدار من verification.py لكن ناتجه يُحزم هنا) ───────


# ── 7: الإصدار ────────────────────────────────────────────────────────────


class ReleaseDept:
    """قسم الإصدار — فرع ورقعة وتقرير هندسي وتذكرة تشغيلية وطلب موافقة.

    القاعدة الحاسمة: ``publish_allowed=False`` دائمًا هنا، والدمج قرار
    موافقة بشرية صريحة عبر ``OrgStore.decide_approval`` — لا مسار ذاتي.
    """

    def __init__(self, runtime: AgentRuntime, org_store: OrgStore,
                 ops_store: OpsStore, outdir: Path,
                 runner: WorkspaceRunner | None = None) -> None:
        self.runtime = runtime
        self.org_store = org_store
        self.ops_store = ops_store
        self.outdir = Path(outdir)
        self.runner = runner

    def run(self, ctx: MissionContext) -> dict[str, Any]:
        mission = ctx.mission
        outdir = self.outdir / mission.id   # مجلد لكل مهمة — معزول حتميًا
        outdir.mkdir(parents=True, exist_ok=True)
        branch = f"org/{mission.id}"
        patch_path = outdir / "patch.diff"
        patch_path.write_text(ctx.diff_text, encoding="utf-8")
        pr_text = self._pr_text(ctx)
        report_path = outdir / "REPORT.md"
        report_path.write_text(self._report_md(ctx, branch, pr_text),
                               encoding="utf-8")
        ticket_bundle = self.open_ticket(ctx, branch, report_path)
        statement = (f"تقرير ورقعة جاهزان عند {self.outdir} وتذكرة "
                     f"{ticket_bundle['ticket'].id} بانتظار موافقة بشرية")
        claim = Claim(
            mission_id=mission.id, agent_role="release:engineer",
            statement=statement, claim_kind="observation",
            id=new_id("org-c", mission.id, "release:engineer", statement))
        ctx.claims.append(claim)
        self.runtime.store.add_evidence(Evidence(
            mission_id=mission.id, kind="log",
            detail={"report_path": str(report_path),
                    "patch_path": str(patch_path),
                    "ticket_id": ticket_bundle["ticket"].id},
            captured_by="release:engineer", ok=True, claim_id=claim.id))
        ctx.pr_text = pr_text
        return {"status": "ok", "branch": branch,
                "patch_path": str(patch_path),
                "report_path": str(report_path),
                "ticket_id": ticket_bundle["ticket"].id,
                "approval_id": ticket_bundle["approval"].id,
                "publish_allowed": ticket_bundle["ticket"].publish_allowed,
                "claim": claim}

    def open_ticket(self, ctx: MissionContext, branch: str,
                    report_path: Path) -> dict[str, Any]:
        """فتح تذكرة تشغيلية مرتبطة — publish_allowed=False مثبت."""
        report = {
            "what": f"رقعة {ctx.mission.title} على "
                    f"{', '.join(ctx.changed_files) or 'ملفات معلنة'}",
            "why": ctx.mission.objective[:300],
            "risk": "; ".join(
                f"{r.get('severity')}: {r.get('message')}"
                for r in ctx.dev_risks) or "لا مخاطر معلنة من التطوير",
            "tests": self._tests_summary(ctx),
            "rollback": "استرجاع الرقعة بعكس الفرق — لا تغييرات خارج نسخة العمل",
        }
        from src.ops.contracts import Ticket
        ticket = self.ops_store.add_ticket(Ticket(
            origin="manual", title=f"[org] {ctx.mission.title}",
            report=report))
        approval = self.org_store.request_approval(Approval(
            mission_id=ctx.mission.id, kind="merge", subject=ticket.id,
            note=f"فرع {branch} — التقرير: {report_path.name}"))
        return {"ticket": ticket, "approval": approval}

    def _pr_text(self, ctx: MissionContext) -> dict[str, Any]:
        spec = AgentSpec(role="release:engineer", dept="release",
                         mission_id=ctx.mission.id, max_retries=1)
        prompt = (f"MISSION: {ctx.mission.title}\nOBJECTIVE: "
                  f"{ctx.mission.objective}\nDIFF:\n{ctx.diff_text[:4000]}\n"
                  "أجب JSON بمفاتيح: pr_title، pr_body_sections.")
        outcome = self.runtime.ask_json(spec, prompt)
        ctx.add_usage(outcome)
        if outcome.success:
            return outcome.data
        return {"pr_title": f"org: {ctx.mission.title}",
                "pr_body_sections": ["ما تغيّر", "لماذا", "المخاطر",
                                     "الاختبارات", "التراجع"]}

    def _tests_summary(self, ctx: MissionContext) -> str:
        parts: list[str] = []
        for label in ("baseline_tests", "patched_tests"):
            data = getattr(ctx, label) or {}
            detail = data.get("detail", {})
            parts.append(f"{label}: rc={detail.get('returncode', '?')}")
        return "; ".join(parts) or "لا اختبارات مُشغَّلة"

    def _report_md(self, ctx: MissionContext, branch: str,
                   pr_text: dict[str, Any]) -> str:
        """التقرير الهندسي الحتمي — ما تغيّر ولماذا والمخاطر والاختبارات."""
        mission = ctx.mission
        council = ctx.council
        sec = ctx.security_report.get("counts", {})
        # المعايير تُقرأ من المخزن — كائن الحقيبة قد يسبق تثبيتها
        stored = self.runtime.store.mission_get(mission.id)
        criteria = stored.acceptance_criteria if stored else mission.acceptance_criteria
        lines = [
            f"# تقرير هندسي — {mission.id}",
            "",
            f"**العنوان:** {mission.title}",
            f"**الهدف:** {mission.objective}",
            f"**الفرع:** `{branch}`",
            "",
            "## معايير القبول",
        ]
        lines += [f"- {c}" for c in criteria] or ["- (غير مستخرجة)"]
        lines += ["", "## ما تغيّر"]
        lines += [f"- `{p}`" for p in ctx.changed_files] or ["- لا ملفات"]
        lines += [
            "",
            "## المراجعة المستقلة",
            f"- القرار: {council.verdict if council else 'لم يُجرَ'} "
            f"(متوسط {council.mean_score if council else 0})",
        ]
        if council:
            lines += [f"- سبب: {r}" for r in council.reasons[:5]]
        lines += [
            "",
            "## الأمن",
            f"- أسرار: {sec.get('secrets', 0)} · تبعيات مُصابة: "
            f"{sec.get('vulnerable_dependencies', 0)} · حقن: "
            f"{sec.get('injections', 0)} · تهديد: {sec.get('threat_hits', 0)}",
            "",
            "## الاختبارات",
            f"- الأساس: {self._tests_summary(ctx)}",
            "",
            "## طلب السحب المقترح",
            f"**{pr_text.get('pr_title', '')}**",
        ]
        lines += [f"- {s}" for s in pr_text.get("pr_body_sections", [])]
        lines += [
            "",
            "## الادعاءات والأدلة",
        ]
        stored_claims = self.runtime.store.claims_for(mission.id)
        shown = stored_claims or ctx.claims
        for claim in shown:
            lines.append(f"- [{claim.status}] {claim.statement}")
        lines += [
            "",
            "## الدمج",
            "- بوابة الدمج بشرية: تذكرة تشغيلية مع publish_allowed=False،",
            "  والموافقة تسجَّل في approvals باسم صانع القرار وزمنه.",
        ]
        return "\n".join(lines)


# ── مجمّع الأقسام ─────────────────────────────────────────────────────────


class Departments:
    """مجمّع الأقسام الثمانية — بناء واحد بأسلاك مشتركة معلنة."""

    def __init__(
        self, pool: ProviderPool, org_store: OrgStore,
        ops_store: OpsStore, outdir: str | Path = "reports/org",
        coder_connector_factory: Callable[[AgentRuntime, str], Any] | None = None,
    ) -> None:
        self.pool = pool
        self.org_store = org_store
        self.ops_store = ops_store
        self.outdir = Path(outdir)
        self.guard = InjectionGuard()
        self.tools = build_tool_registry(Path("."), self.guard)
        self.runner = WorkspaceRunner()
        self.runtime = AgentRuntime(pool, self.tools, org_store)
        self.requirements = RequirementsOffice(self.runtime)
        self.intel = RepoIntelDept(self.runtime, self.guard)
        self.development = DevelopmentDept(self.runtime, coder_connector_factory)
        self.security = SecurityDept(self.runtime, self.guard)
        self.qa = QADept(self.runner, org_store)
        self.council = ReviewCouncil(self.runtime, org_store)
        self.release = ReleaseDept(self.runtime, org_store, ops_store,
                                   self.outdir, self.runner)

    def verify_tooling(self) -> dict[str, bool]:
        """فحص جاهزية معلن — أدوات معلنة ومشغّل عزل يعمل."""
        return {
            "tools": all(self.tools.has(n) for n in ("read_repo",
                                                     "security_scan")),
            "sandbox": self.runner.run_python("print('ok')").returncode == 0,
        }
