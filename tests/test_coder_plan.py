"""RepairPlan schema tests (M2.3) — validation rules and JSON round-trip."""

from __future__ import annotations

from src.coder.plan import RepairPlan, Step, plan_from_json, validate


def _plan(**overrides: object) -> RepairPlan:
    base: dict = {
        "goal": "add helper",
        "defects": ["missing helper"],
        "steps": [Step(file="src/util.py", action="create",
                       reason="new helper module", patch_hint="def help() -> int:\n    return 1")],
        "tests_to_run": ["tests/test_util.py"],
    }
    base.update(overrides)
    return RepairPlan(**base)  # type: ignore[arg-type]


def test_valid_plan_has_no_errors() -> None:
    assert validate(_plan()) == []


def test_missing_goal() -> None:
    assert "missing goal" in validate(_plan(goal=""))


def test_no_steps() -> None:
    assert "plan has no steps" in validate(_plan(steps=[]))


def test_no_tests_declared() -> None:
    assert "plan declares no tests" in validate(_plan(tests_to_run=[]))


def test_bad_action() -> None:
    plan = _plan(steps=[Step(file="a.py", action="rewrite", reason="r", patch_hint="x")])
    assert any("bad action" in e for e in validate(plan))


def test_bad_risk_level() -> None:
    plan = _plan(steps=[Step(file="a.py", action="edit", reason="r", patch_hint="x", risk="urgent")])
    assert any("bad risk level" in e for e in validate(plan))


def test_unsafe_absolute_path() -> None:
    plan = _plan(steps=[Step(file="/etc/passwd", action="edit", reason="r", patch_hint="x")])
    assert any("unsafe path" in e for e in validate(plan))


def test_unsafe_escaping_path() -> None:
    plan = _plan(steps=[Step(file="../outside.py", action="edit", reason="r", patch_hint="x")])
    assert any("unsafe path" in e for e in validate(plan))


def test_empty_file_path() -> None:
    plan = _plan(steps=[Step(file="", action="edit", reason="r", patch_hint="x")])
    assert any("unsafe path" in e for e in validate(plan))


def test_missing_patch_hint_on_edit_and_create() -> None:
    edit = _plan(steps=[Step(file="a.py", action="edit", reason="r", patch_hint="")])
    create = _plan(steps=[Step(file="a.py", action="create", reason="r", patch_hint="")])
    assert any("patch_hint" in e for e in validate(edit))
    assert any("patch_hint" in e for e in validate(create))


def test_missing_reason_on_edit_and_delete() -> None:
    edit = _plan(steps=[Step(file="a.py", action="edit", reason="", patch_hint="x")])
    delete = _plan(steps=[Step(file="a.py", action="delete", reason="", patch_hint="")])
    assert any("reason" in e for e in validate(edit))
    assert any("reason" in e for e in validate(delete))


def test_delete_needs_no_patch_hint() -> None:
    plan = _plan(steps=[Step(file="a.py", action="delete", reason="dead code")])
    assert validate(plan) == []


def test_to_json_round_trip() -> None:
    plan = _plan()
    restored = plan_from_json(plan.to_json())
    assert restored == plan
    assert restored.to_json()["steps"][0]["file"] == "src/util.py"


def test_plan_from_json_tolerates_garbage() -> None:
    plan = plan_from_json({"steps": ["not-a-dict", 42, None],
                           "defects": "oops", "tests_to_run": "also-not-a-list"})
    assert plan.steps == []
    # non-list defect/test payloads are dropped, not split into characters
    assert plan.defects == []
    assert plan.tests_to_run == []
    assert plan.goal == ""


def test_plan_from_json_maps_step_fields() -> None:
    plan = plan_from_json({
        "goal": "g",
        "steps": [{"file": "a.py", "action": "create", "reason": "r",
                   "patch_hint": "x", "risk": "high"}],
        "tests_to_run": ["t.py"],
    })
    assert plan.steps[0].risk == "high"
    assert validate(plan) == []
