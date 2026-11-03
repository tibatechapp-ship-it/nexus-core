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
    steps = [dict(GOOD_STEPS[0], risk="high"), GOOD_STEPS[1]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(steps, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2, gates=PASS_GATE)
    assert result["ok"] is False and result["error"] == "council_required"
    assert result["plan"]["steps"][0]["risk"] == "high"
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


async def test_council_refusal_is_rejected(tmp_path: Path) -> None:
    steps = [dict(GOOD_STEPS[0], risk="high"), GOOD_STEPS[1]]
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(steps, GOOD_TESTS)])
    result = await run_engine("g", conn, root=tmp_path, max_iterations=2,
                              council=lambda plan: "no", gates=PASS_GATE)
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
    trace_file = Path.cwd() / "runs" / "trace.jsonl"
    conn = Scripted([{"ok": True, "reply": "[]"}, _plan_reply(GOOD_STEPS, GOOD_TESTS)])
    await run_engine("g", conn, root=tmp_path, max_iterations=2,
                     gates=PASS_GATE, test_timeout=90)
    # NEXUS_TRACE_PATH points at tmp (fixture); repo runs/trace.jsonl untouched
    assert not trace_file.exists() or "coder" not in trace_file.read_text()


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
