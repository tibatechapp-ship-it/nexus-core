"""Escalation governance tests (ب1.1–ب1.3) — خطة التناغم docs/harmony-plan.md.

العقد المعلن: المجلس لا يُستشار استباقياً في وضع ``escalate`` (الافتراضي
الجديد)؛ يُستشار مرة واحدة عند العجز (محاولتان فاشلتان)، حكمه يصير
feedback لا أمراً بإيقاف، وفشل المداولة نفسها لا يهدم المحرك.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.coder.engine import run_engine
from src.coder.policy import COUNCIL_MODES, ESCALATE_AFTER_FAILURES

PY = sys.executable
PASS_GATE: list = [[PY, "-c", "pass"]]


class Scripted:
    """Connector double: pops scripted replies in order (نمط test_coder_engine)."""

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


def _plan_reply(steps: list, tests: list) -> dict:
    return {"ok": True, "reply": json.dumps(
        {"goal": "make add work", "defects": [],
         "steps": steps, "tests_to_run": tests})}


GOOD_STEPS = [
    {"file": "mathlib.py", "action": "create", "reason": "core helper",
     "patch_hint": "def add(a: int, b: int) -> int:\n    return a + b\n", "risk": "low"},
    {"file": "test_mathlib.py", "action": "create", "reason": "prove it",
     "patch_hint": "from mathlib import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n",
     "risk": "low"},
]
GOOD_TESTS = ["test_mathlib.py"]
HIGH_STEPS = [
    {"file": "mathlib.py", "action": "create", "reason": "core helper",
     "patch_hint": "def add(a: int, b: int) -> int:\n    return a + b\n", "risk": "high"},
    GOOD_STEPS[1],
]


class CouncilDouble:
    """مجلس مضاعف: يسجل كل نداء ويعيد حكماً مبرمجاً (أو يفجّر استثناء)."""

    def __init__(self, verdict: str = "approve", explode: bool = False) -> None:
        self.verdict = verdict
        self.explode = explode
        self.calls: list = []

    def __call__(self, plan: object) -> str:
        self.calls.append(plan)
        if self.explode:
            raise RuntimeError("council exploded")
        return self.verdict


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_TRACE_PATH", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("NEXUS_QUALITY_GATE_LOG", str(tmp_path / "gate.jsonl"))


def test_escalate_is_a_declared_mode_and_the_default() -> None:
    """ب1.1: escalate معلن في الأوضاع الأربع — والافتراضي في run_engine هو هو."""
    assert COUNCIL_MODES == ("escalate", "async", "blocking", "off")
    assert ESCALATE_AFTER_FAILURES == 2
    import inspect

    from src.coder import engine

    sig = inspect.signature(engine.run_engine)
    assert sig.parameters["council_mode"].default == "escalate"


async def test_escalate_mode_never_deliberates_proactively(tmp_path: Path) -> None:
    """ب1.1: خطة عالية الخطر ناجحة في المحاولة الأولى ⇒ صفر مداولة + pending."""
    council = CouncilDouble("approve")
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    assert len(council.calls) == 0  # لا استباقية — المجلس لم يُستشار إطلاقاً
    assert result["promotion"] == "pending"  # توقيع صريح لاحق هو البوابة
    assert result["escalation"] == {"triggered": False, "iteration": 0, "verdict": ""}


async def test_escalation_fires_once_after_two_failures(tmp_path: Path) -> None:
    """ب1.2: فشلان ⇒ مداولة واحدة في المحاولة الثالثة، وحكمه صار feedback."""
    council = CouncilDouble("focus on the failing gate first")
    conn = Scripted([
        {"ok": True, "reply": "[]"},                     # detect
        {"ok": True, "reply": "{goal: broken}"},         # it1: خطة غير JSON (فشل 1)
        {"ok": False, "error": "no plan"},               # it2: فشل تخطيط (عجز 2)
        _plan_reply(GOOD_STEPS, GOOD_TESTS),             # it3: بعد التصعيد
    ])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    assert result["iterations"] == 3
    assert len(council.calls) == 1  # استدعاء واحد بالضبط — لا تكرار
    assert result["escalation"]["triggered"] is True
    assert result["escalation"]["iteration"] == 3
    assert result["escalation"]["verdict"] == "focus on the failing gate first"
    # حكم المجلس صار جزءاً من feedback المحاولة التالية (يحلّ لا يوقف)
    third_prompt = conn.calls[-1]
    assert "council escalation: focus on the failing gate first" in third_prompt


async def test_escalation_verdict_approves_high_risk(tmp_path: Path) -> None:
    """ب1.2: تصعيد على هدف عالي الخطر وحكم approve ⇒ ترقية معتمدة."""
    council = CouncilDouble("approve")
    conn = Scripted([
        {"ok": True, "reply": "[]"},
        {"ok": True, "reply": "{goal: broken}"},         # it1: فشل 1
        {"ok": False, "error": "no plan"},               # it2: عجز 2
        _plan_reply(HIGH_STEPS, GOOD_TESTS),             # it3: بعد التصعيد
    ])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True
    assert result["escalation"]["triggered"] is True
    assert result["promotion"] == "approved"


async def test_council_crash_does_not_break_engine(tmp_path: Path) -> None:
    """ب1.3: فشل المداولة نفسها لا يهدم المحرك — الخطأ يُسجَّل مقصوصاً."""
    council = CouncilDouble(explode=True)
    conn = Scripted([
        {"ok": True, "reply": "[]"},
        {"ok": True, "reply": "{goal: broken}"},         # it1: فشل 1
        {"ok": False, "error": "no plan"},               # it2: عجز 2
        _plan_reply(GOOD_STEPS, GOOD_TESTS),             # it3: بعد تصعيد فاشل
    ])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=3,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True  # المحرك سليم رغم انفجار المجلس
    assert result["escalation"]["triggered"] is True
    assert result["escalation"]["verdict"].startswith("error: RuntimeError")


async def test_escalate_low_risk_stays_auto(tmp_path: Path) -> None:
    """ب1.1: خطرة منخفضة في escalate ⇒ auto كما كانت — لا تغيير على السليم."""
    council = CouncilDouble("approve")
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1,
                              council=council, gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and result["promotion"] == "auto"
    assert len(council.calls) == 0


async def test_async_mode_still_deliberates_in_parallel(tmp_path: Path) -> None:
    """العقد القديم محفوظ: async يبقى مداولة متوازية لكل خطة عالية."""
    council = CouncilDouble("approve")
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(HIGH_STEPS, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=1,
                              council=council, council_mode="async",
                              gates=PASS_GATE, test_timeout=90)
    assert result["ok"] is True and len(council.calls) == 1
    assert result["promotion"] == "approved"
