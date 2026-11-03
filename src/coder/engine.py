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
from src.observability.trace import trace_event
from src.quality_gate.runner import run_gate

COUNCIL_APPROVALS = frozenset({"approve", "approved", "ok", "yes"})
MAX_ITERATIONS = 5
MAX_FEEDBACK = 400

PLAN_PROMPT = (
    "You are the planning stage of a coding agent. Reply with ONLY one JSON "
    'object: {"goal": str, "defects": [str], "steps": [{"file": str, '
    '"action": "edit"|"create"|"delete", "reason": str, "patch_hint": str, '
    '"risk": "low"|"medium"|"high"}], "tests_to_run": [str]}.\n'
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


def _council_required(plan: RepairPlan) -> bool:
    """M2.5 acceptance: any high-risk step needs a council decision first."""
    return any(step.risk == "high" for step in plan.steps)


def _summarize(results: list) -> str:
    """One-line gate summary for the next iteration's feedback."""
    failed = [r for r in results if not r.get("ok")]
    if not failed:
        return "gate green"
    return "; ".join(f"{r['cmd']}: {r.get('tail', '')[-120:]}" for r in failed[:2])


async def _run_engine(goal: str, connector: Any, root: Path, workdir: Path,
                      max_iterations: int, council: Callable | None,
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

        if _council_required(plan):
            decision = str(council(plan)) if council else None
            if decision not in COUNCIL_APPROVALS:
                trace_event("coder", "council", outcome="rejected")
                return {"ok": False, "error": "council_required", "iterations": iteration,
                        "plan": plan.to_json(), "attempts": attempts, "workdir": str(workdir)}
            trace_event("coder", "council", outcome="approved")

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
            trace_event("coder", "gate", outcome="ok",
                        duration_ms=round((time.monotonic() - started) * 1000, 2))
            return {"ok": True, "iterations": iteration, "plan": plan.to_json(),
                    "gate": gate_results, "workdir": str(workdir), "attempts": attempts}
        feedback = "gate failed: " + _summarize(gate_results) + f" | tests: {tests['stderr'][-120:]}"
        trace_event("coder", "gate", outcome="fail")

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
    gates: list | None = None,
    test_timeout: int = 60,
) -> JsonDict:
    """Run the five-stage loop; mutations land only inside ``workdir``.

    ``connector`` is any BYOK object exposing ``async generate()``; ``council``
    is an optional callable consulted for high-risk plans (None + high risk =
    automatic rejection). Returns a JSON result whose ``attempts`` list is the
    full audit trail of every iteration's stage outcomes.
    """
    root = Path(root)
    wd = Path(workdir) if workdir is not None else sandbox.new_workdir()
    wd.mkdir(parents=True, exist_ok=True)
    try:
        return await _run_engine(goal, connector, root, wd, max_iterations,
                                 council, gates, test_timeout)
    except Exception as exc:  # noqa: BLE001 — the engine reports, never crashes the caller
        trace_event("coder", "engine", outcome="fail", extra={"error": str(exc)[:200]})
        return {"ok": False, "error": f"engine crashed: {exc}"[:MAX_FEEDBACK]}
