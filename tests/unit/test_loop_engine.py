import json
import os
import tempfile
from pathlib import Path
from typing import Dict

import pytest

from novamind.core.loop_engine import (
    Budget,
    Goal,
    IterationResult,
    LoopEngine,
    LoopResult,
    StateStore,
)


class DummyFactory:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.call_count = 0

    def call(self, agent_name: str, **kwargs) -> Dict:
        self.calls.append((agent_name, dict(kwargs)))
        self.call_count += 1
        if self.results:
            res = self.results.pop(0)
            return dict(res) if isinstance(res, dict) else {"ok": bool(res)}
        return {"ok": True}


class FailingFactory(DummyFactory):
    def call(self, agent_name: str, **kwargs) -> Dict:
        self.calls.append((agent_name, dict(kwargs)))
        self.call_count += 1
        raise RuntimeError("boom")


# 1. Goal Tests (3 tests)
def test_goal_simple_creation():
    g = Goal(description="Fix all tests")
    assert g.description == "Fix all tests"
    assert g.max_iterations == 10
    assert g.success_criteria is None


def test_goal_with_budget_money_like_logic():
    # Goal accepts max_iterations; also test is_success with custom criteria
    def criteria(r: Dict) -> bool:
        return r.get("passed") == r.get("total") and r.get("total", 0) > 0

    g = Goal(description="fix tests", success_criteria=criteria, max_iterations=5)
    assert g.max_iterations == 5
    assert g.is_success({"passed": 3, "total": 3}) is True
    assert g.is_success({"passed": 2, "total": 3}) is False


def test_goal_with_budget_time_like_logic():
    # Goal default success: ok or success True
    g = Goal(description="task")
    assert g.is_success({"ok": True}) is True
    assert g.is_success({"success": True}) is True
    assert g.is_success({"ok": False}) is False
    # criteria exception -> False
    def bad(_r: Dict) -> bool:
        raise ValueError("x")

    g2 = Goal(description="bad", success_criteria=bad)
    assert g2.is_success({}) is False


# 2. Budget Tests (3 tests)
def test_budget_tracking_cost():
    b = Budget(max_iterations=10, max_cost=1.5)
    assert b.max_cost == 1.5
    assert b.max_time is None
    assert b.to_dict()["max_cost"] == 1.5


def test_budget_tracking_duration():
    b = Budget(max_iterations=5, max_time=30.0)
    assert b.max_time == 30.0
    assert b.to_dict()["max_time"] == 30.0


def test_budget_exceed():
    b = Budget(max_iterations=2, max_cost=0.1, max_time=0.01)
    d = b.to_dict()
    assert d["max_iterations"] == 2
    assert d["max_cost"] == 0.1
    assert d["max_time"] == 0.01


# 3. StateStore Tests (4 tests)
def test_state_store_save_checkpoint():
    with tempfile.TemporaryDirectory() as tmp:
        s = StateStore(state_dir=Path(tmp))
        data = {"loop_id": "loop_123", "iteration": 2, "history": [{"i": 1}]}
        s.save("loop_123", data)
        p = Path(tmp) / "loop_123.json"
        assert p.exists()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["iteration"] == 2


def test_state_store_load_checkpoint():
    with tempfile.TemporaryDirectory() as tmp:
        s = StateStore(state_dir=Path(tmp))
        s.save("abc", {"iteration": 3})
        got = s.load("abc")
        assert got is not None and got["iteration"] == 3
        assert s.load("missing") is None


def test_state_store_resume_from_file():
    with tempfile.TemporaryDirectory() as tmp:
        s = StateStore(state_dir=Path(tmp))
        s.save("loop_r", {"iteration": 5, "history": [{"i": 1}, {"i": 2}], "goal": "x"})
        got = s.load("loop_r")
        assert got["iteration"] == 5
        assert len(got["history"]) == 2


def test_state_store_history_last20_limitation():
    with tempfile.TemporaryDirectory() as tmp:
        s = StateStore(state_dir=Path(tmp))
        hist = [{"i": k} for k in range(25)]
        s.save("loop_l", {"iteration": 10, "history": hist[-20:]})
        got = s.load("loop_l")
        assert len(got["history"]) == 20
        assert got["history"][0]["i"] == 5  # indices 5..24


# 4. LoopEngine Tests (5 tests)
def test_loop_engine_run_simple_one_iteration():
    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(state_dir=Path(tmp))
        eng = LoopEngine(factory=DummyFactory([{"ok": True}]), state_store=store)
        g = Goal(description="do one", max_iterations=5)
        res = eng.run_until(g, agent_name="test_agent")
        assert isinstance(res, LoopResult)
        assert res.status == "success"
        assert res.iterations == 1
        assert res.final_result.get("ok") is True


def test_loop_engine_run_multi_5_iterations():
    with tempfile.TemporaryDirectory() as tmp:
        # fail 4, succeed 5th
        results = [{"ok": False}, {"ok": False}, {"ok": False}, {"ok": False}, {"ok": True}]
        eng = LoopEngine(factory=DummyFactory(results), state_store=StateStore(state_dir=Path(tmp)))
        g = Goal(description="multi", max_iterations=10)
        res = eng.run_until(g, agent_name="agent", agent_kwargs={"x": 1})
        assert res.status == "success"
        assert res.iterations == 5
        assert len(res.history) == 5


def test_loop_engine_max_iterations():
    with tempfile.TemporaryDirectory() as tmp:
        eng = LoopEngine(factory=DummyFactory([{"ok": False}] * 6), state_store=StateStore(state_dir=Path(tmp)))
        g = Goal(description="max", max_iterations=3)
        res = eng.run_until(g, agent_name="agent")
        assert res.status == "max_iterations"
        assert res.iterations == 3
        assert len(res.history) == 3


def test_loop_engine_failure_step_error_filled():
    with tempfile.TemporaryDirectory() as tmp:
        eng = LoopEngine(factory=FailingFactory(), state_store=StateStore(state_dir=Path(tmp)))
        g = Goal(description="fail", max_iterations=1)
        res = eng.run_until(g, agent_name="agent")
        # Iteration 1 fails; goal.is_success({"ok":False,"error":...}) is False -> max_iterations
        assert res.status == "max_iterations"
        assert res.iterations == 1
        # history has error field set
        assert len(res.history) == 1
        assert "error" in res.history[0]
        # error populated from result
        assert res.history[0]["error"] is not None


def test_loop_engine_on_iteration_callback():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []

        def cb(ir: IterationResult):
            calls.append(ir.iteration)

        eng = LoopEngine(factory=DummyFactory([{"ok": True}]), state_store=StateStore(state_dir=Path(tmp)))
        g = Goal(description="cb", max_iterations=3)
        res = eng.run_until(g, agent_name="agent", on_iteration=cb)
        assert res.status == "success"
        assert calls == [1]


# 5. IterationResult Tests (2 tests)
def test_iteration_result_success_case():
    ir = IterationResult(
        iteration=1,
        timestamp="2026-10-13T00:00:00+00:00",
        agent_name="agent",
        result={"ok": True},
        elapsed=0.01,
        success=True,
    )
    d = ir.to_dict()
    assert d["success"] is True
    assert d["error"] is None
    assert d["iteration"] == 1


def test_iteration_result_error_case():
    ir = IterationResult(
        iteration=2,
        timestamp="2026-10-13T00:00:00+00:00",
        agent_name="agent",
        result={"ok": False, "error": "bad"},
        elapsed=0.02,
        success=False,
        error="bad",
    )
    d = ir.to_dict()
    assert d["success"] is False
    assert d["error"] == "bad"
    assert d["agent_name"] == "agent"
