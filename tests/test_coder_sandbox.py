"""Sandbox tests (M2.4) — path safety, rlimits subprocess, replay records."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.coder.plan import Step
from src.coder.plan import RepairPlan
from src.coder.sandbox import (apply_plan, cleanup, export_record, new_workdir,
                               run_cmd, run_tests)

PY = sys.executable


def _plan(steps: list) -> RepairPlan:
    return RepairPlan(goal="g", defects=[], steps=steps,
                      tests_to_run=["test_x.py"])


def test_new_workdir_is_isolated_and_empty() -> None:
    a, b = new_workdir(), new_workdir()
    assert a != b and a.exists() and not list(a.iterdir())
    cleanup(a)
    cleanup(b)
    assert not a.exists()


def test_apply_plan_create_makes_parents(tmp_path: Path) -> None:
    plan = _plan([Step(file="pkg/sub/mod.py", action="create",
                       reason="r", patch_hint="x = 1\n")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is True
    assert (tmp_path / "pkg" / "sub" / "mod.py").read_text() == "x = 1\n"


def test_apply_plan_edit_appends(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("first\n")
    plan = _plan([Step(file="a.py", action="edit", reason="r", patch_hint="second\n")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is True
    assert "first\nsecond\n" in (tmp_path / "a.py").read_text()


def test_apply_plan_delete_removes(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("bye\n")
    plan = _plan([Step(file="a.py", action="delete", reason="dead")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is True
    assert not (tmp_path / "a.py").exists()


def test_apply_plan_delete_missing_file_is_ok(tmp_path: Path) -> None:
    plan = _plan([Step(file="ghost.py", action="delete", reason="r")])
    assert apply_plan(plan, tmp_path)["ok"] is True


def test_apply_plan_rejects_escaping_path(tmp_path: Path) -> None:
    plan = _plan([Step(file="../escape.py", action="create", reason="r", patch_hint="x")])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is False
    assert "escapes sandbox" in res["errors"][0]["error"]
    assert not (tmp_path.parent / "escape.py").exists()


def test_apply_plan_rejects_oversized_file(tmp_path: Path) -> None:
    plan = _plan([Step(file="big.py", action="create", reason="r",
                       patch_hint="x" * (256 * 1024 + 1))])
    res = apply_plan(plan, tmp_path)
    assert res["ok"] is False
    assert "size cap" in res["errors"][0]["error"]


def test_run_cmd_success_and_failure(tmp_path: Path) -> None:
    ok = run_cmd([PY, "-c", "print('hello')"], tmp_path)
    assert ok["ok"] is True and "hello" in ok["stdout"] and ok["timeout"] is False
    bad = run_cmd([PY, "-c", "raise SystemExit(3)"], tmp_path)
    assert bad["ok"] is False and bad["exit_code"] == 3


def test_run_cmd_timeout_kills(tmp_path: Path) -> None:
    res = run_cmd([PY, "-c", "import time; time.sleep(30)"], tmp_path, timeout=1)
    assert res["ok"] is False and res["timeout"] is True and res["exit_code"] is None


def test_run_cmd_timeout_is_clamped(tmp_path: Path) -> None:
    res = run_cmd([PY, "-c", "print('quick')"], tmp_path, timeout=99999)
    assert res["ok"] is True  # clamped to MAX_TIMEOUT_S, still runs


def test_run_cmd_spawn_failure(tmp_path: Path) -> None:
    res = run_cmd(["/no/such/binary-anywhere"], tmp_path)
    assert res["ok"] is False and "spawn failed" in res["stderr"]


def test_run_cmd_caps_output(tmp_path: Path) -> None:
    res = run_cmd([PY, "-c", "print('x' * 200000)"], tmp_path)
    assert len(res["stdout"]) <= 64 * 1024


def test_run_tests_green_and_red(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_ok() -> None:\n    assert 1 == 1\n")
    good = run_tests(["test_x.py"], tmp_path, timeout=60)
    assert good["ok"] is True and good["tests"] == ["test_x.py"]
    (tmp_path / "test_x.py").write_text("def test_bad() -> None:\n    assert 1 == 2\n")
    bad = run_tests(["test_x.py"], tmp_path, timeout=60)
    assert bad["ok"] is False


def test_export_record_is_replayable_jsonl(tmp_path: Path) -> None:
    plan = _plan([Step(file="a.py", action="create", reason="r", patch_hint="x")])
    line = export_record(plan, tmp_path, {"verdict": "green"})
    data = json.loads(line)
    assert data["plan"]["goal"] == "g"
    assert data["outcome"] == {"verdict": "green"}
    assert data["workdir"] == str(tmp_path)


@pytest.mark.parametrize("bad_path", ["/absolute.py", "a/../../up.py"])
def test_safe_target_rejects(tmp_path: Path, bad_path: str) -> None:
    from src.coder.sandbox import _safe_target
    with pytest.raises(ValueError, match="escapes sandbox"):
        _safe_target(tmp_path, bad_path)


def test_make_limits_applies_the_three_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """CPU/FSIZE/NPROC caps are requested — setrlimit is MOCKED because a real
    call would re-limit the WHOLE pytest process (threads + CPU) and poison
    every later test in the suite."""
    import resource

    import src.coder.sandbox as sb

    seen: list = []
    monkeypatch.setattr(sb.resource, "setrlimit", lambda res, lim: seen.append((res, lim)))
    sb._make_limits()
    assert (resource.RLIMIT_CPU, (60, 60)) in seen
    assert (resource.RLIMIT_FSIZE, (5 * 1024 * 1024, 5 * 1024 * 1024)) in seen
    assert (resource.RLIMIT_NPROC, (64, 64)) in seen
    assert len(seen) == 3


def test_make_limits_tolerates_platform_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A platform refusing setrlimit must not crash the sandbox bootstrap."""
    import src.coder.sandbox as sb

    def refuse(res: int, limits: tuple) -> None:
        raise ValueError("rlimit denied by platform")

    monkeypatch.setattr(sb.resource, "setrlimit", refuse)
    sb._make_limits()  # swallows the refusal and returns
