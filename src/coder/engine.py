"""Five-stage coding engine — analyze → detect → plan → execute → gate.

حلقة محرك البرمجة (مهمة M2.5 فوق M2.1–M2.4): تقرأ المستودع، تكتشف العيوب،
تُلزم النموذج بمخطط RepairPlan صالح قبل أي تعديل، تنفّذ داخل صندوق معزول،
ثم تسلّم لبوابة الجودة المستقلة. التعديل عالي الخطورة بلا قرار مجلس
يُرفض آليًا (بند قبول M2.5)، وكل مرحلة تُسجَّل في سجل الأثر المعياري.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.coder import sandbox
from src.coder.analyzer import analyze_repo
from src.coder.detector import detect
from src.coder.plan import RepairPlan, plan_from_json, validate
from src.coder.policy import RiskPolicy
from src.observability.trace import trace_event
from src.quality_gate.runner import run_gate

COUNCIL_APPROVALS = frozenset({"approve", "approved", "ok", "yes"})
MAX_ITERATIONS = 5
MAX_FEEDBACK = 400
DEFAULT_COUNCIL_TIMEOUT = 30.0

#: أوضاع المجلس — راجع ``src/coder/policy.py`` للشرح الكامل.
#: ``async`` هو المعيار الجديد: لا توقف عمل، ومداولة متوازية، وبوابة ترقية.
COUNCIL_MODES = ("async", "blocking", "off")

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


async def _council_verdict(council: Callable, plan: RepairPlan) -> str:
    """استدعاء المجلس داعماً للمزامن وغير المتزامن — نص القرار كما عاد."""
    result = council(plan)
    if asyncio.iscoroutine(result):
        result = await result
    return str(result)


def _start_council(council: Callable | None, plan: RepairPlan) -> asyncio.Task | None:
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


async def _run_engine(goal: str, connector: Any, root: Path, workdir: Path,
                      max_iterations: int, council: Callable | None,
                      council_mode: str, council_timeout: float,
                      policy: RiskPolicy,
                      gates: list | None, test_timeout: int) -> JsonDict:
    context = analyze_repo(root)
    trace_event("coder", "analyze", extra={"summary": context["summary"]})
    defects = await detect(connector, goal, {**context, "root": str(root)})
    trace_event("coder", "detect", outcome="ok", extra={"defects": str(len(defects))})
    feedback = ""
    attempts: list = []

    for iteration in range(1, max_iterations + 1):
        started = time.monotonic()
        plan, error = await _ask_plan(connector, goal, defects, context, feedback)
        if plan is None:
            feedback = error
            attempts.append({"iteration": iteration, "stage": "plan", "error": error})
            trace_event("coder", "plan", outcome="fail", extra={"error": error})
            continue
        errors = validate(plan)
        if errors:
            feedback = "fix plan errors: " + "; ".join(errors)
            attempts.append({"iteration": iteration, "stage": "plan", "error": feedback})
            trace_event("coder", "plan", outcome="fail", extra={"error": feedback})
            continue
        trace_event("coder", "plan", outcome="ok",
                    extra={"steps": str(len(plan.steps)), "iteration": str(iteration)})

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
                        "promotion": promotion, "workdir": str(workdir)}
            trace_event("coder", "council", outcome="approved")
        elif high_risk and council_mode == "async":
            # المعيار الجديد: مداولة متوازية — التنفيذ لا ينتظر أحداً.
            council_task = _start_council(council, plan)
            trace_event("coder", "council", outcome="started")

        execution = sandbox.apply_plan(plan, workdir)
        if not execution["ok"]:
            feedback = "sandbox rejected steps: " + json.dumps(execution["errors"])[:MAX_FEEDBACK]
            attempts.append({"iteration": iteration, "stage": "execute", "error": feedback})
            trace_event("coder", "execute", outcome="fail")
            continue

        tests = sandbox.run_tests(plan.tests_to_run, workdir, timeout=test_timeout)
        gate_ok, gate_results = run_gate(workdir, gates=gates)
        attempts.append({
            "iteration": iteration, "stage": "gate", "tests_ok": tests["ok"],
            "gate_ok": gate_ok, "gate": gate_results,
        })
        _append_record(workdir, plan, {"tests": tests, "gate": gate_results})
        if tests["ok"] and gate_ok:
            promotion = "auto"
            if high_risk:
                if council_mode == "off":
                    promotion = "pending"
                    trace_event("coder", "council", outcome="skipped",
                                extra={"mode": "off"})
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
            trace_event("coder", "gate", outcome="ok",
                        duration_ms=round((time.monotonic() - started) * 1000, 2))
            return {"ok": True, "iterations": iteration, "plan": plan.to_json(),
                    "gate": gate_results, "promotion": promotion,
                    "workdir": str(workdir), "attempts": attempts}
        feedback = "gate failed: " + _summarize(gate_results) + f" | tests: {tests['stderr'][-120:]}"
        trace_event("coder", "gate", outcome="fail")
        if council_task is not None:
            council_task.cancel()

    return {"ok": False, "error": "max_iterations", "iterations": max_iterations,
            "attempts": attempts, "workdir": str(workdir)}


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
    council_mode: str = "async",
    council_timeout: float = DEFAULT_COUNCIL_TIMEOUT,
    policy: RiskPolicy | None = None,
    gates: list | None = None,
    test_timeout: int = 60,
) -> JsonDict:
    """Run the five-stage loop; mutations land only inside ``workdir``.

    ``connector`` is any BYOK object exposing ``async generate()``. ``council``
    is an optional callable (sync or async). ``council_mode`` chooses how the
    council is involved: ``"async"`` (default — deliberation runs in parallel
    with execution, work never stops, the verdict lands in ``promotion``),
    ``"blocking"`` (legacy — high-risk plans wait for an explicit approval),
    or ``"off"`` (never consulted; high-risk results stay ``pending``).
    ``policy`` scopes *when* the council is consulted at all (effective risk
    by path and action — docs/tests never wake the council). Returns a JSON
    result whose ``attempts`` list is the full audit trail of every
    iteration's stage outcomes.
    """
    if council_mode not in COUNCIL_MODES:
        raise ValueError(f"council_mode must be one of {COUNCIL_MODES}, "
                         f"got {council_mode!r}")
    root = Path(root)
    wd = Path(workdir) if workdir is not None else sandbox.new_workdir()
    wd.mkdir(parents=True, exist_ok=True)
    active_policy = policy if policy is not None else RiskPolicy()
    try:
        return await _run_engine(goal, connector, root, wd, max_iterations,
                                 council, council_mode, council_timeout,
                                 active_policy, gates, test_timeout)
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
