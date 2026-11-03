"""Five-stage engine tests (M2.5) — scripted connector, hermetic end-to-end."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.coder.engine import run_engine

PY = sys.executable
PASS_GATE: list = [[PY, "-c", "pass"]]


class Scripted:
    """Connector double: pops scripted replies in order, records prompts."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls: list = []

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        self.calls.append(prompt)
        if not self.replies:
            return {"ok": False, "error": "script exhausted"}
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Boom:
    """Connector whose generate() always raises (engine must contain it)."""

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        raise RuntimeError("connector exploded")


def _plan_reply(steps: list, tests: list, defects: list | None = None) -> dict:
    return {"ok": True, "reply": json.dumps(
        {"goal": "make add work", "defects": defects or [],
         "steps": steps, "tests_to_run": tests})}


GOOD_STEPS = [
    {"file": "mathlib.py", "action": "create", "reason": "core helper",
     "patch_hint": "def add(a: int, b: int) -> int:\n    return a + b\n", "risk": "low"},
    {"file": "test_mathlib.py", "action": "create", "reason": "prove it",
     "patch_hint": "from mathlib import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n",
     "risk": "low"},
]
GOOD_TESTS = ["test_mathlib.py"]


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("NEXUS_QUALITY_GATE_LOG", str(tmp_path / "gate.jsonl"))


async def test_happy_path_green_gate(tmp_path: Path) -> None:
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("make add work", conn, root=tmp_path, max_iterations=2,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True, result
    assert result["iterations"] == 1
    assert result["plan"]["steps"][0]["file"] == "mathlib.py"
    assert all(g["ok"] for g in result["gate"])
    # the two files really exist inside the isolated workdir, repo untouched
    assert (Path(result["workdir"]) / "mathlib.py").exists()
    assert not (tmp_path / "mathlib.py").exists()


async def test_invalid_plan_gets_feedback_then_succeeds(tmp_path: Path) -> None:
    invalid = _plan_reply(GOOD_STEPS, [])  # no tests declared
    conn = Scripted([{"ok": True, "reply": "[]"}, invalid,
                     _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3, gates=PASS_GATE)
    assert result["ok"] is True and result["iterations"] == 2
    plan_attempt = next(a for a in result["attempts"] if a["stage"] == "plan")
    assert "declares no tests" in plan_attempt["error"]
    assert "declares no tests" in conn.calls[2]  # feedback reached the next prompt


async def test_model_failure_then_recovery(tmp_path: Path) -> None:
    conn = Scripted([{"ok": True, "reply": "[]"}, {"ok": False, "error": "endpoint down"},
                     _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3, gates=PASS_GATE)
    assert result["ok"] is True and result["iterations"] == 2


async def test_max_iterations_reported(tmp_path: Path) -> None:
    conn = Scripted([{"ok": False, "error": "down"}] * 4)
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2, gates=PASS_GATE)
    assert result["ok"] is False and result["error"] == "max_iterations"
    assert result["iterations"] == 2
    assert len(result["attempts"]) == 2 and "workdir" in result


async def test_sandbox_rejection_feedback(tmp_path: Path) -> None:
    huge = "x" * (256 * 1024 + 1)  # valid plan, oversized file → apply fails
    steps = [{"file": "big.py", "action": "create", "reason": "r",
              "patch_hint": huge, "risk": "low"}]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(steps, ["t.py"])])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1, gates=PASS_GATE)
    assert result["ok"] is False and result["iterations"] == 1
    assert result["attempts"][0]["stage"] == "execute"
    assert "sandbox rejected" in result["attempts"][0]["error"]


async def test_failing_tests_block_success(tmp_path: Path) -> None:
    bad_steps = [dict(GOOD_STEPS[0]),
                 {"file": "test_mathlib.py", "action": "create", "reason": "prove it",
                  "patch_hint": "from mathlib import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 4\n",
                  "risk": "low"}]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(bad_steps, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is False
    attempt = result["attempts"][0]
    assert attempt["stage"] == "gate" and attempt["tests_ok"] is False
    record = (Path(result["workdir"]) / "runs" / "engine.jsonl").read_text()
    assert json.loads(record.splitlines()[-1])["plan"]["goal"] == "make add work"


async def test_high_risk_without_council_is_rejected(tmp_path: Path) -> None:
    """الوضع المقيد (blocking): بلا مجلس ⇒ رفض قبل التنفيذ — عقد قديم محفوظ."""
    steps = [dict(GOOD_STEPS[0], risk="high"), GOOD_STEPS[1]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(steps, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council_mode="blocking", gates=PASS_GATE)
    assert result["ok"] is False and result["error"] == "council_required"
    assert result["plan"]["steps"][0]["risk"] == "high"
    assert result["promotion"] == "pending"
    # the rejected plan never touched the sandbox
    assert not (Path(result["workdir"]) / "mathlib.py").exists()


async def test_council_approval_lets_high_risk_proceed(tmp_path: Path) -> None:
    steps = [dict(GOOD_STEPS[0], risk="high"), GOOD_STEPS[1]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(steps, GOOD_TESTS)])
    seen: list = []

    def council(plan: object) -> str:
        seen.append(plan)
        return "approve"

    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and len(seen) == 1
    assert result["promotion"] == "approved"


async def test_council_refusal_is_rejected(tmp_path: Path) -> None:
    """blocking + رفض صريح ⇒ إيقاف قبل التنفيذ (النظام المقيد يبقى مقيداً)."""
    steps = [dict(GOOD_STEPS[0], risk="high"), GOOD_STEPS[1]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(steps, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=lambda plan: "no",
                              council_mode="blocking", gates=PASS_GATE)
    assert result["ok"] is False and result["error"] == "council_required"


async def test_connector_crash_is_contained(tmp_path: Path) -> None:
    result = await run_engine("g", Boom(), root=tmp_path, max_iterations=1, gates=PASS_GATE)
    assert result["ok"] is False
    assert result["error"].startswith("engine crashed")
    assert "connector exploded" in result["error"]


async def test_model_plan_without_json_is_feedback(tmp_path: Path) -> None:
    conn = Scripted([{"ok": True, "reply": "[]"}, {"ok": True, "reply": "I will fix it, trust me"},
                     _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3, gates=PASS_GATE)
    assert result["ok"] is True
    assert "did not return a JSON plan" in conn.calls[2]


async def test_trace_records_every_stage(tmp_path: Path) -> None:
    """كل مرحلة تُسجَّل في ملف الأثر الموجَّه بالفكستر (tmp) — حصرية كاملة:
    الاختبار لا يقرأ جذر المستودع إطلاقاً فلا يتأثر بسجلات التشغيل المحلية."""
    trace_file = tmp_path / "trace.jsonl"
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    events = [json.loads(line) for line in trace_file.read_text().splitlines()
              if line.strip()]
    stages = [(e["agent"], e["tool"], e["outcome"]) for e in events]
    assert stages == [("coder", "analyze", "ok"), ("coder", "detect", "ok"),
                      ("coder", "plan", "ok"), ("quality-gate", "run", "ok"),
                      ("coder", "gate", "ok")]
    required = {"ts", "agent", "tool", "duration_ms", "outcome"}
    assert all(required <= set(e) for e in events)


async def test_explicit_workdir_is_reused(tmp_path: Path) -> None:
    wd = tmp_path / "fixed-wd"
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, workdir=wd,
                              max_iterations=2, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    assert result["workdir"] == str(wd)
    assert (wd / "mathlib.py").exists()


async def test_model_plan_with_broken_json_is_feedback(tmp_path: Path) -> None:
    conn = Scripted([{"ok": True, "reply": "[]"}, {"ok": True, "reply": "{goal: broken}"},
                     {"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3, gates=PASS_GATE)
    assert result["ok"] is True and result["iterations"] == 3
    assert "not valid JSON" in conn.calls[2]


async def test_failing_gate_blocks_success(tmp_path: Path) -> None:
    bad_gate: list = [[PY, "-c", "raise SystemExit(1)"]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1,
                              gates=bad_gate, test_timeout=90)
    assert result["ok"] is False
    attempt = result["attempts"][0]
    assert attempt["tests_ok"] is True and attempt["gate_ok"] is False


async def test_engine_record_failure_is_tolerated(tmp_path: Path) -> None:
    wd = tmp_path / "wd"
    (wd / "runs").mkdir(parents=True)
    (wd / "runs" / "engine.jsonl").mkdir()  # log path is a directory → OSError
    conn = Scripted([{"ok": True, "reply": "[]"},
                     _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, workdir=wd, max_iterations=2,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True  # best-effort record never breaks the engine


# ─── M4: المجلس سلطة ترقية لا سلطة إيقاف ────────────────────────────────────

HIGH_STEPS = [dict(GOOD_STEPS[0], risk="high"), GOOD_STEPS[1]]


async def test_async_default_work_never_stops(tmp_path: Path) -> None:
    """الافتراضي الجديد: مخاطر عالية بلا مجلس ⇒ العمل يكتمل في العزل."""
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    assert result["promotion"] == "pending"
    assert (Path(result["workdir"]) / "mathlib.py").exists()  # العمل أُنجز فعلاً
    trace = (tmp_path / "trace.jsonl").read_text()
    assert '"outcome": "pending"' in trace or '"outcome":"pending"' in trace


async def test_async_council_approve_overlaps_execution(tmp_path: Path) -> None:
    """المداولة تمضي بالتوازي: الموافقة تصل قبل نهاية البوابة فترفَع approved."""
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=lambda plan: "approve",
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "approved"


async def test_async_council_reject_flags_but_does_not_stop(tmp_path: Path) -> None:
    """رفض المجلس في الوضع الجديد: العمل جاهز لكن الترقية مرفوضة دائماً."""
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=lambda plan: "veto",
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "rejected"
    from src.coder.engine import promote
    assert promote(result)["ok"] is False  # لن يُنشر مهما فعل الطالب


async def test_async_slow_council_times_out_to_pending(tmp_path: Path) -> None:
    """مجلس بطيء: المحرك لا يعلق — المهلة تُرجع pending والعمل محفوظ."""
    import asyncio as _aio

    async def slow_council(plan: object) -> str:
        await _aio.sleep(5)
        return "approve"

    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=slow_council, council_timeout=0.05,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "pending"


async def test_async_broken_council_yields_pending(tmp_path: Path) -> None:
    """مجلس ينفجر: المداولة تُحتى والعمل يبقى سالماً بترقية pending."""
    def exploding_council(plan: object) -> str:
        raise RuntimeError("council chamber collapsed")

    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=exploding_council,
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "pending"


async def test_policy_scopes_council_to_real_risk(tmp_path: Path) -> None:
    """المجلس لا يُستشار إلا للخطر الحقيقي: توثيق موسوم عالياً لا يوقظه."""
    docs_only = [GOOD_STEPS[0],
                 {"file": "docs/guide.md", "action": "create", "reason": "r",
                  "patch_hint": "# guide\n", "risk": "high"},
                 GOOD_STEPS[1]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(docs_only, GOOD_TESTS)])
    calls: list = []

    def council(plan: object) -> str:
        calls.append(plan)
        return "approve"

    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    assert calls == []  # السياسة منعته من الوصول للمجلس أصلاً
    assert result["promotion"] == "auto"


async def test_policy_always_flags_deletion_and_protected(tmp_path: Path) -> None:
    """الحذف والمسارات المحمية خطورة عقيقة مهما وسّمها النموذج."""
    from src.coder.plan import RepairPlan, Step
    from src.coder.policy import RiskPolicy

    policy = RiskPolicy()
    plan = RepairPlan(goal="g", defects=[], steps=[
        Step(file="legacy.py", action="delete", reason="r", patch_hint="", risk="low"),
        Step(file=".env.local", action="edit", reason="r",
             patch_hint="x=1", risk="low"),
    ], tests_to_run=[])
    assert policy.high_risk_steps(plan) == ["legacy.py", ".env.local"]


async def test_promote_gate_rules() -> None:
    """بوابة الترقية: الفاشل مرفوض، auto/approved يمر، pending يحتاج توقيعاً."""
    from src.coder.engine import promote

    assert promote({"ok": False, "error": "max_iterations"})["ok"] is False
    assert promote({"ok": True, "promotion": "auto"})["ok"] is True
    assert promote({"ok": True, "promotion": "approved"})["ok"] is True
    pending = {"ok": True, "promotion": "pending"}
    assert promote(pending)["ok"] is False
    cleared = promote(pending, signed_off=True)
    assert cleared["ok"] is True and "sign-off" in cleared["reason"]
    assert promote({"ok": True, "promotion": "rejected"},
                   signed_off=True)["ok"] is False
    assert promote({"ok": True})["ok"] is True  # غياب الحقل = قديم سليم


async def test_invalid_council_mode_is_rejected(tmp_path: Path) -> None:
    conn = Scripted([{"ok": True, "reply": "[]"}])
    with pytest.raises(ValueError, match="council_mode"):
        await run_engine("g", conn, root=tmp_path, gates=PASS_GATE,
                         council_mode="mob_rule")


async def test_blocking_approve_traces_and_proceeds(tmp_path: Path) -> None:
    """blocking + موافقة: يُتتبَّع approved ويُنفَّذ (عقد القديم كامل)."""
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=lambda plan: "ok",
                              council_mode="blocking", gates=PASS_GATE,
                              test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "approved"
    trace = (tmp_path / "trace.jsonl").read_text()
    assert '"outcome": "approved"' in trace or '"outcome":"approved"' in trace


async def test_off_mode_skips_council_keeps_work_pending(tmp_path: Path) -> None:
    """off: لا استشارة إطلاقاً، والعمل عالي الخطورة يبقى بانتظار توقيع."""
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    calls: list = []

    def council(plan: object) -> str:
        calls.append(plan)
        return "approve"

    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=council, council_mode="off",
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "pending"
    assert calls == []  # لم يُستشار أصلاً
    trace = (tmp_path / "trace.jsonl").read_text()
    assert "skipped" in trace


async def test_failing_gate_cancels_pending_council(tmp_path: Path) -> None:
    """بوابة فاشلة مع مداولة جارية: تُلغى المهمة ولا تسرّب مهما كان."""
    import asyncio as _aio

    finished: list = []

    async def slow_council(plan: object) -> str:
        await _aio.sleep(5)
        finished.append(True)
        return "approve"

    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1,
                              council=slow_council, council_timeout=5,
                              gates=[[PY, "-c", "raise SystemExit(1)"]],
                              test_timeout=90)
    assert result["ok"] is False and result["error"] == "max_iterations"
    await _aio.sleep(0)  # فرصة لتنفيذ الإلغاء
    assert finished == []  # المداولة أُلغيت لا أُكمِل في الخلفية


def test_promotion_helper_direct() -> None:
    from src.coder.engine import _promotion

    assert _promotion("x", high_risk=False) == "auto"
    assert _promotion("approve", high_risk=True) == "approved"
    assert _promotion("DENY", high_risk=True) == "rejected"
    assert _promotion("maybe", high_risk=True) == "pending"
