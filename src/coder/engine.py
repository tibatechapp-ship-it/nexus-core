"""Five-stage coding engine — analyze → detect → plan → execute → gate.

حلقة محرك البرمجة (مهمة M2.5 فوق M2.1–M2.4): تقرأ المستودع، تكتشف العيوب،
تُلزم النموذج بمخطط RepairPlan صالح قبل أي تعديل، تنفّذ داخل صندوق معزول،
ثم تسلّم لبوابة الجودة المستقلة. التعديل عالي الخطورة بلا قرار مجلس
يُرفض آليًا (بند قبول M2.5)، وكل مرحلة تُسجَّل في سجل الأثر المعياري.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.coder import sandbox
from src.coder.analyzer import analyze_repo
from src.coder.context import build_code_context
from src.coder.container_sandbox import run_in_container
from src.coder.detector import detect
from src.coder.plan import RepairPlan, plan_from_json, validate
from src.coder.reviewer import review_patch
from src.coder.policy import ESCALATE_AFTER_FAILURES, RiskPolicy
from src.observability.trace import trace_event
from src.quality_gate.runner import run_gate

COUNCIL_APPROVALS = frozenset({"approve", "approved", "ok", "yes"})
MAX_ITERATIONS = 5
MAX_FEEDBACK = 400
DEFAULT_COUNCIL_TIMEOUT = 30.0

#: أوضاع المجلس — راجع ``src/coder/policy.py`` للشرح الكامل.
#: ``escalate`` هو المعيار الجديد (v1.61.0): لا مداولة استباقية — تصعيد واحد
#: عند العجز فقط، ودور المجلس الدائم مراقبة وتقييم عبر ``src.council.monitor``.
COUNCIL_MODES = ("escalate", "async", "blocking", "off")

PLAN_PROMPT = (
    "You are the planning stage of a coding agent. Reply with ONLY one JSON "
    'object: {"goal": str, "defects": [str], "steps": [{"file": str, '
    '"action": "edit"|"create"|"delete", "reason": str, "patch_hint": str, '
    '"find": str, "risk": "low"|"medium"|"high"}], "tests_to_run": [str]}.\n'
    'For "edit" steps "find" MUST be the exact unique text being replaced; '
    'use "" for create/delete steps.\n'
)

JsonDict = dict


async def _ask_plan(connector: Any, goal: str, defects: list, context: dict,
                    feedback: str) -> tuple:
    """Stage 3: get a RepairPlan from the model, or a failure reason."""
    # Built by concatenation: the JSON shape inside the prompt holds literal
    # braces that str.format() would try to interpret as replacement fields.
    prompt = (
        PLAN_PROMPT
        + f"Goal: {goal}\n"
        + f"Repo map: {context.get('summary', '')}\n"
        + "Relevant source files (read-only evidence):\n"
        + str(context.get("source_context", "(not available)"))[:24000]
        + "\nUse the actual code above; do not invent files, APIs, or dependencies. "
        + "For edits, make the find block exact and unique, and preserve surrounding behavior.\n"
        + f"Defects: {json.dumps(defects, ensure_ascii=False)[:1200]}\n"
        + f"Feedback from the previous attempt: {feedback or 'none'}\n"
    )
    reply = await connector.generate(prompt)
    if not reply.get("ok"):
        return None, str(reply.get("error", "model call failed"))[:MAX_FEEDBACK]
    match = re.search(r"\{.*\}", str(reply.get("reply", "")), re.DOTALL)
    if not match:
        return None, "model did not return a JSON plan"
    try:
        plan = plan_from_json(json.loads(match.group(0)))
    except json.JSONDecodeError:
        return None, "model plan is not valid JSON"
    return plan, ""


async def _council_verdict(council: Callable, plan: RepairPlan | None) -> str:
    """استدعاء المجلس داعماً للمزامن وغير المتزامن — نص القرار كما عاد.

    الخطة قد تكون غائبة (``None``) حين كان العجز في مرحلة التخطيط نفسها —
    والمجلس عندنا يُستشار بسياق العجز لا بالخطة وحدها (ب1.2).
    """
    result = council(plan)
    if asyncio.iscoroutine(result):
        result = await result
    return str(result)


def _start_council(council: Callable | None,
                   plan: RepairPlan | None) -> asyncio.Task | None:
    """إطلاق مداولة المجلس كمهمة متوازية — لا تنتظرها الحلقة الآن."""
    if council is None:
        return None
    return asyncio.ensure_future(_council_verdict(council, plan))


async def _await_council(task: asyncio.Task | None,
                         timeout: float) -> str:
    """حصاد قرار المجلس: النص، أو ``timeout`` إن تأخر، أو ``error`` إن فشل."""
    if task is None:
        return "none"
    try:
        return str(await asyncio.wait_for(asyncio.shield(task), timeout=timeout))
    except asyncio.TimeoutError:
        task.cancel()
        return "timeout"
    except Exception as exc:  # noqa: BLE001 — فشل المداولة لا يهدم المحرك
        return f"error: {type(exc).__name__}: {exc}"[:MAX_FEEDBACK]


def _promotion(verdict: str, *, high_risk: bool) -> str:
    """ترجمة قرار المجلس إلى حالة ترقية معلنة.

    ``auto``: لا مخاطر عالية — الترقية لا تحتاج أحداً. ``approved``: موافقة
    صريحة. ``rejected``: رفض صريح. ``pending``: عملٌ أُنجز في العزل وبقي
    بانتظار توقيع (لا يُنشر حتى يصله).
    """
    if not high_risk:
        return "auto"
    lowered = verdict.strip().lower()
    if lowered in COUNCIL_APPROVALS:
        return "approved"
    if lowered in {"no", "reject", "rejected", "deny", "denied", "veto"}:
        return "rejected"
    return "pending"


def _summarize(results: list) -> str:
    """One-line gate summary for the next iteration's feedback."""
    failed = [r for r in results if not r.get("ok")]
    if not failed:
        return "gate green"
    return "; ".join(f"{r['cmd']}: {r.get('tail', '')[-120:]}" for r in failed[:2])


def _workspace_patch(root: Path, workdir: Path, limit: int = 80_000) -> str:
    """Build a bounded text diff between the original repository and workdir."""
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist",
               "build", ".next", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    sensitive = {".env", ".env.local", ".env.production", "credentials", "secrets",
                 "id_rsa", "id_ed25519"}
    def collect(base: Path) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for current, dirs, files in os.walk(base, topdown=True, followlinks=False):
            dirs[:] = [name for name in dirs if name not in ignored and not name.startswith(".")]
            for name in files:
                path = Path(current) / name
                if path.is_symlink() or name.lower() in sensitive or name.lower().startswith(".env"):
                    continue
                try:
                    if path.stat().st_size <= 64 * 1024:
                        found[path.relative_to(base).as_posix()] = path
                except OSError:
                    continue
        return found

    original, candidate = collect(root), collect(workdir)
    chunks: list[str] = []
    used = 0
    for name in sorted(set(original) | set(candidate)):
        try:
            old = original[name].read_text(encoding="utf-8") if name in original else ""
            new = candidate[name].read_text(encoding="utf-8") if name in candidate else ""
        except (OSError, UnicodeError):
            continue
        if old == new:
            continue
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{name}", tofile=f"b/{name}",
        ))
        if diff:
            remaining = limit - used
            if remaining <= 0:
                break
            chunks.append(diff[:remaining])
            used += min(len(diff), remaining)
    return "".join(chunks)


async def _run_engine(goal: str, connector: Any, root: Path, workdir: Path,
                      max_iterations: int, council: Callable | None,
                      council_mode: str, council_timeout: float,
                      policy: RiskPolicy,
                      gates: list | None, test_timeout: int,
                      execution_mode: str, container_image: str | None,
                      container_enabled: bool, container_approved: bool,
                      reviewer: Callable | None, author_provider_id: str,
                      reviewer_provider_id: str) -> JsonDict:
    context = analyze_repo(root)
    trace_event("coder", "analyze", extra={"summary": context["summary"]})
    defects = await detect(connector, goal, {**context, "root": str(root)})
    source_context = build_code_context(root, context, defects, goal=goal)
    context["source_context"] = source_context["rendered"]
    trace_event("coder", "context", outcome="ok", extra={
        "files": str(len(source_context["files"])),
        "characters": str(source_context["characters"]),
        "truncated": str(source_context["truncated"]),
        "retrieval": str(source_context.get("retrieval", "deterministic")),
    })
    trace_event("coder", "detect", outcome="ok", extra={"defects": str(len(defects))})
    feedback = ""
    attempts: list = []
    last_plan: RepairPlan | None = None
    failures = 0
    escalated = False
    escalation: JsonDict = {"triggered": False, "iteration": 0, "verdict": ""}

    for iteration in range(1, max_iterations + 1):
        started = time.monotonic()
        # ب1.2 — التصعيد عند العجز (وضع escalate فقط): بعد ESCALATE_AFTER_FAILURES
        # محاولة فاشلة في التشغيل نفسه يُستشار المجلس مرة واحدة بسياق العجز،
        # ليحلّ لا ليوقف — نص حكمه يصير feedback المحاولة التالية.
        if (council_mode == "escalate" and council is not None
                and not escalated and failures >= ESCALATE_AFTER_FAILURES):
            escalated = True
            escalation = {"triggered": True, "iteration": iteration, "verdict": ""}
            trace_event("coder", "council", outcome="escalated",
                        extra={"failures": str(failures)})
            verdict = await _await_council(_start_council(council, last_plan),
                                           council_timeout)
            escalation["verdict"] = verdict
            tail = feedback[-MAX_FEEDBACK // 2:]
            feedback = f"council escalation: {verdict} | previous: {tail}" if feedback \
                else f"council escalation: {verdict}"

        plan, error = await _ask_plan(connector, goal, defects, context, feedback)
        if plan is None:
            failures += 1
            feedback = error
            attempts.append({"iteration": iteration, "stage": "plan", "error": error})
            trace_event("coder", "plan", outcome="fail", extra={"error": error})
            continue
        errors = validate(plan)
        if errors:
            failures += 1
            feedback = "fix plan errors: " + "; ".join(errors)
            attempts.append({"iteration": iteration, "stage": "plan", "error": feedback})
            trace_event("coder", "plan", outcome="fail", extra={"error": feedback})
            continue
        trace_event("coder", "plan", outcome="ok",
                    extra={"steps": str(len(plan.steps)), "iteration": str(iteration)})
        last_plan = plan

        high_risk = policy.needs_council(plan)
        council_task = None
        blocking_verdict: str | None = None
        if high_risk and council_mode == "blocking":
            # الوضع القديم المقيد: لا تنفيذ قبل حكم صريح — للأنظمة التي تطلبه.
            blocking_verdict = await _await_council(_start_council(council, plan),
                                                    council_timeout)
            promotion = _promotion(blocking_verdict, high_risk=True)
            if blocking_verdict not in COUNCIL_APPROVALS:
                trace_event("coder", "council", outcome="rejected")
                return {"ok": False, "error": "council_required", "iterations": iteration,
                        "plan": plan.to_json(), "attempts": attempts,
                        "promotion": promotion, "workdir": str(workdir),
                        "escalation": escalation}
            trace_event("coder", "council", outcome="approved")
        elif high_risk and council_mode == "async":
            # الوضع القديم المتاح: مداولة متوازية — التنفيذ لا ينتظر أحداً.
            council_task = _start_council(council, plan)
            trace_event("coder", "council", outcome="started")
        elif high_risk and council_mode == "escalate":
            # المعيار الجديد (ب1.1): لا مداولة استباقية — الخطة تُنفّذ وتبقى
            # pending حتى توقيع صريح، إلا إذا سبق تصعيدٌ حكمَ على الهدف.
            trace_event("coder", "council", outcome="deferred",
                        extra={"mode": "escalate"})

        execution = sandbox.apply_plan(plan, workdir)
        if not execution["ok"]:
            failures += 1
            feedback = "sandbox rejected steps: " + json.dumps(execution["errors"])[:MAX_FEEDBACK]
            attempts.append({"iteration": iteration, "stage": "execute", "error": feedback})
            trace_event("coder", "execute", outcome="fail")
            continue

        if execution_mode == "container":
            tests = run_in_container(
                ["python", "-m", "pytest", "-q", "--no-header", *plan.tests_to_run],
                workdir, image=container_image or "", enabled=container_enabled,
                approved=container_approved, timeout=test_timeout,
            )
            gate_ok, gate_results = run_gate(
                workdir, gates=gates, container_image=container_image,
                container_enabled=container_enabled, container_approved=container_approved,
            )
        else:
            tests = sandbox.run_tests(plan.tests_to_run, workdir, timeout=test_timeout)
            gate_ok, gate_results = run_gate(workdir, gates=gates)
        attempts.append({
            "iteration": iteration, "stage": "gate", "tests_ok": tests["ok"],
            "gate_ok": gate_ok, "gate": gate_results,
        })
        _append_record(workdir, plan, {"tests": tests, "gate": gate_results})
        if tests["ok"] and gate_ok:
            review_result = None
            if reviewer is not None:
                try:
                    patch_text = _workspace_patch(root, workdir)
                    review_result = await review_patch(
                        patch_text,
                        json.dumps({
                            "goal": goal, "plan": plan.to_json(),
                            "tests": tests, "quality_gates": gate_results,
                        }, ensure_ascii=False)[:40000],
                        reviewer,
                        author_provider_id=author_provider_id,
                        reviewer_provider_id=reviewer_provider_id,
                    )
                    attempts.append({
                        "iteration": iteration, "stage": "independent_review",
                        "decision": review_result["decision"],
                        "findings": len(review_result["findings"]),
                    })
                    trace_event("coder", "independent_review",
                                outcome=review_result["decision"])
                except Exception as exc:  # noqa: BLE001 — invalid review blocks promotion
                    failures += 1
                    feedback = f"independent review failed: {type(exc).__name__}: {exc}"[:MAX_FEEDBACK]
                    attempts.append({"iteration": iteration, "stage": "independent_review",
                                     "error": feedback})
                    trace_event("coder", "independent_review", outcome="fail")
                    continue
                if review_result["decision"] == "reject":
                    return {"ok": False, "error": "independent_review_rejected",
                            "review": review_result, "iterations": iteration,
                            "attempts": attempts, "workdir": str(workdir),
                            "escalation": escalation}
                if review_result["decision"] != "approve":
                    failures += 1
                    feedback = "independent reviewer requested changes: " + review_result["summary"][:MAX_FEEDBACK]
                    continue
            if high_risk:
                if council_mode == "off":
                    promotion = "pending"
                    trace_event("coder", "council", outcome="skipped",
                                extra={"mode": "off"})
                elif council_mode == "escalate":
                    # ب1.1: بلا تصعيد سابق ⇒ pending؛ مع تصعيد ⇒ حكمه يُحتسب.
                    verdict = escalation["verdict"] if escalated else "none"
                    promotion = _promotion(verdict, high_risk=True)
                    outcome = {"approved": "approved", "rejected": "rejected"}.get(
                        promotion, "pending")
                    trace_event("coder", "council", outcome=outcome,
                                extra={"mode": "escalate", "escalated": str(escalated)})
                else:
                    if council_mode == "blocking":
                        # الحكم سبق وجُوبِض قبل التنفيذ — لا انتظار ثانٍ.
                        promotion = _promotion(blocking_verdict or "none",
                                               high_risk=True)
                    else:
                        verdict = await _await_council(council_task, council_timeout)
                        promotion = _promotion(verdict, high_risk=True)
                    outcome = {"approved": "approved", "rejected": "rejected"}.get(
                        promotion, "pending")
                    trace_event("coder", "council", outcome=outcome,
                                extra={"promotion": promotion})
            else:
                promotion = "auto"
            trace_event("coder", "gate", outcome="ok",
                        duration_ms=round((time.monotonic() - started) * 1000, 2))
            return {"ok": True, "iterations": iteration, "plan": plan.to_json(),
                    "gate": gate_results, "promotion": promotion,
                    "workdir": str(workdir), "attempts": attempts,
                    "review": review_result, "escalation": escalation}
        failures += 1
        feedback = "gate failed: " + _summarize(gate_results) + f" | tests: {tests['stderr'][-120:]}"
        trace_event("coder", "gate", outcome="fail")
        if council_task is not None:
            council_task.cancel()

    return {"ok": False, "error": "max_iterations", "iterations": max_iterations,
            "attempts": attempts, "workdir": str(workdir),
            "escalation": escalation}


def _append_record(workdir: Path, plan: RepairPlan, outcome: dict) -> None:
    """Replayable JSONL record of one executed plan (M2.4 acceptance)."""
    log = workdir / "runs" / "engine.jsonl"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(sandbox.export_record(plan, workdir, outcome) + "\n")
    except OSError:
        pass  # the record is best-effort; never break the engine


async def run_engine(
    goal: str,
    connector: Any,
    *,
    root: Path | str = ".",
    workdir: Path | str | None = None,
    max_iterations: int = MAX_ITERATIONS,
    council: Callable | None = None,
    council_mode: str = "escalate",
    council_timeout: float = DEFAULT_COUNCIL_TIMEOUT,
    policy: RiskPolicy | None = None,
    gates: list | None = None,
    test_timeout: int = 60,
    execution_mode: str = "process",
    container_image: str | None = None,
    container_enabled: bool = False,
    container_approved: bool = False,
    reviewer: Callable | None = None,
    author_provider_id: str = "",
    reviewer_provider_id: str = "",
    require_independent_review: bool = False,
) -> JsonDict:
    """Run the five-stage loop; mutations land only inside ``workdir``.

    ``execution_mode="container"`` runs tests and quality gates only through\n    the rootless Docker sandbox; it requires explicit feature opt-in, human\n    approval and an immutable image digest. The legacy process mode remains\n    available for trusted local development only.\n\n    ``connector`` is any BYOK object exposing ``async generate()``. ``council``
    is an optional callable (sync or async). ``council_mode`` chooses how the
    council is involved: ``"escalate"`` (default — no preemption: work never
    waits, high-risk green results stay ``pending`` for explicit sign-off,
    and the council is consulted exactly once after
    ``ESCALATE_AFTER_FAILURES`` failed attempts — its verdict becomes the
    next iteration's feedback and lands in result ``escalation``),
    ``"async"`` (legacy — parallel deliberation on every high-risk plan),
    ``"blocking"`` (legacy — high-risk plans wait for an explicit approval),
    or ``"off"`` (never consulted; high-risk results stay ``pending``).
    The council's permanent monitoring/evaluating duty lives in
    ``src.council.monitor``. Returns a JSON result whose ``attempts`` list
    is the full audit trail of every iteration's stage outcomes, and whose
    ``escalation`` records whether the impasse escalation fired, at which
    iteration, and its verdict.
    """
    if require_independent_review and reviewer is None:
        raise ValueError("independent reviewer is required but not configured")
    if reviewer is not None and (not author_provider_id or not reviewer_provider_id):
        raise ValueError("author_provider_id and reviewer_provider_id are required with reviewer")
    if execution_mode not in {"process", "container"}:
        raise ValueError("execution_mode must be process or container")
    if execution_mode == "container" and not container_image:
        raise ValueError("container_image pinned by sha256 digest is required")
    if council_mode not in COUNCIL_MODES:
        raise ValueError(f"council_mode must be one of {COUNCIL_MODES}, "
                         f"got {council_mode!r}")
    root = Path(root)
    wd = Path(workdir) if workdir is not None else sandbox.new_workdir()
    wd.mkdir(parents=True, exist_ok=True)
    active_policy = policy if policy is not None else RiskPolicy()
    try:
        workspace_report = sandbox.seed_workspace(root, wd)
        result = await _run_engine(goal, connector, root, wd, max_iterations,
                                   council, council_mode, council_timeout,
                                   active_policy, gates, test_timeout, execution_mode,
                                   container_image, container_enabled, container_approved,
                                   reviewer, author_provider_id, reviewer_provider_id)
        result["workspace"] = workspace_report
        return result
    except Exception as exc:  # noqa: BLE001 — the engine reports, never crashes the caller
        trace_event("coder", "engine", outcome="fail", extra={"error": str(exc)[:200]})
        return {"ok": False, "error": f"engine crashed: {exc}"[:MAX_FEEDBACK]}


def promote(result: JsonDict, *, signed_off: bool = False) -> JsonDict:
    """بوابة النشر الحقيقية — لا شيء يلمس مستودعاً حياً إلا من هنا.

    القواعد المعلنة:

    * نتيجة غير ناجحة (``ok=False``) ⇒ رفض دائم.
    * ``promotion == "auto"`` أو ``"approved"`` ⇒ جاهز للنشر.
    * ``promotion == "pending"`` ⇒ يتطلب ``signed_off=True`` (توقيع مجلس أو
      إنسان) — هذا ما يفصل «العمل المنجز» عن «المنشور».
    * ``promotion == "rejected"`` ⇒ رفض دائم مهما كان التوقيع.

    الإرجاع: ``{"ok": bool, "reason": str}`` — لا يلمس ملفات، القرار للطالب.
    """
    if not result.get("ok"):
        return {"ok": False, "reason": f"engine failed: {result.get('error', 'unknown')}"}
    promotion = result.get("promotion", "auto")
    if promotion in {"auto", "approved"}:
        return {"ok": True, "reason": f"promotion={promotion}"}
    if promotion == "rejected":
        return {"ok": False, "reason": "council rejected this plan"}
    if signed_off:
        return {"ok": True, "reason": "pending promotion cleared by explicit sign-off"}
    return {"ok": False,
            "reason": "promotion pending council sign-off (pass signed_off=True)"}
