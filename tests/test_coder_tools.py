"""Tests for the opt-in, dev-bounded coder MCP tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from src.agent_loop.tools import DEV_TOOLS_ENV
from src.mcp import coder_tools as coder_module
from src.mcp import framework as framework_module
from src.mcp.coder_tools import CoderAuditLog, build_coder_toolkit
from src.mcp.client import content_text

_APPROVAL = "yes"
_PINNED_IMAGE = "alpine@sha256:" + "a" * 64


def _call(toolkit: Any, tool: str, **arguments: Any) -> dict[str, Any]:
    result = toolkit.call(tool, arguments)
    return json.loads(content_text(result))


def _create_plan(file: str = "notes.txt", content: str = "hello") -> dict[str, Any]:
    return {
        "goal": "create a note",
        "defects": [],
        "steps": [
            {
                "file": file,
                "action": "create",
                "reason": "document the change",
                "patch_hint": content,
                "risk": "low",
                "find": "",
            }
        ],
        "tests_to_run": ["pytest"],
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def toolkit(workspace: Path) -> Any:
    return build_coder_toolkit(workspace)


def test_coder_tools_are_opt_in(workspace: Path) -> None:
    default = framework_module.build_framework_server(
        root=workspace, include_agents=False, include_security=False
    )
    default_names = [tool["name"] for tool in default.list_tools()["tools"]]
    assert not any(name.startswith("coder_") for name in default_names)

    dev = framework_module.build_framework_server(
        root=workspace,
        include_agents=False,
        include_security=False,
        include_dev_tools=True,
    )
    dev_names = [tool["name"] for tool in dev.list_tools()["tools"]]
    assert {
        "coder_plan_preview",
        "coder_apply_plan",
        "coder_run_tests",
        "coder_container_run",
    } <= set(dev_names)


def test_preview_is_read_only_and_audited_once(workspace: Path, toolkit: Any) -> None:
    outcome = _call(toolkit, "coder_plan_preview", plan=_create_plan())

    assert outcome["ok"] is True
    assert outcome["mode"] == "read_only"
    assert "hello" in outcome["diff"]
    assert not (workspace / "notes.txt").exists()
    assert len(toolkit.audit.events) == 1
    event = toolkit.audit.events[0].to_dict()
    assert event["tool"] == "coder_plan_preview"
    assert event["permission_mode"] == "read_only"
    assert event["ok"] is True and event["error_code"] is None


def test_apply_plan_requires_env_and_approval(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DEV_TOOLS_ENV, raising=False)
    args = {"plan": _create_plan(), "workspace_root": str(workspace), "approval": _APPROVAL}

    denied = _call(toolkit, "coder_apply_plan", **args)
    assert denied["code"] == coder_module.CODE_DISABLED
    assert not (workspace / "notes.txt").exists()

    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    args["approval"] = "maybe"
    unapproved = _call(toolkit, "coder_apply_plan", **args)
    assert unapproved["code"] == coder_module.CODE_APPROVAL
    assert not (workspace / "notes.txt").exists()
    assert len(toolkit.audit.events) == 2


def test_apply_plan_success_and_audit_clean(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    outcome = _call(
        toolkit,
        "coder_apply_plan",
        plan=_create_plan(),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )

    assert outcome["ok"] is True and outcome["applied"] == ["notes.txt"]
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"
    assert len(toolkit.audit.events) == 1
    blob = json.dumps([event.to_dict() for event in toolkit.audit.events])
    assert set(toolkit.audit.events[0].to_dict()) == {
        "tool",
        "permission_mode",
        "ok",
        "duration_ms",
        "chars",
        "error_code",
    }
    for secret in (_APPROVAL, "notes.txt", "hello", str(workspace)):
        assert secret not in blob


def test_apply_plan_refuses_traversal_sensitive_and_oversize(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")

    outside = _call(
        toolkit,
        "coder_apply_plan",
        plan=_create_plan(file="../evil.txt"),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outside["code"] == coder_module.CODE_PLAN
    assert not (workspace.parent / "evil.txt").exists()

    sensitive = _call(
        toolkit,
        "coder_apply_plan",
        plan=_create_plan(file=".env"),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert sensitive["code"] == coder_module.CODE_WORKSPACE
    assert not (workspace / ".env").exists()

    oversized = _call(
        toolkit,
        "coder_apply_plan",
        plan=_create_plan(content="x" * (coder_module.MAX_FILE_BYTES + 1)),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert oversized["code"] == coder_module.CODE_LIMIT


def test_run_tests_uses_allowlisted_argv(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    (workspace / "a.py").write_text("print(1)\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], root: Path, timeout: Any) -> dict[str, Any]:
        seen["argv"] = argv
        seen["root"] = root
        seen["timeout"] = timeout
        return {"ok": True, "exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(coder_module, "_bounded_command", fake_run)
    outcome = _call(
        toolkit,
        "coder_run_tests",
        command="ruff",
        targets=["a.py"],
        timeout=10,
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )

    assert outcome["ok"] is True and outcome["exit_code"] == 0
    assert seen["argv"] == [sys.executable, "-m", "ruff", "check", "a.py"]
    assert seen["root"] == workspace and seen["timeout"] == 10


def test_run_tests_refusals(workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    (workspace / "a.py").write_text("print(1)\n", encoding="utf-8")
    base = {"workspace_root": str(workspace), "approval": _APPROVAL}

    bad_command = _call(toolkit, "coder_run_tests", command="bash", targets=["a.py"], **base)
    assert bad_command["code"] == coder_module.CODE_COMMAND

    absolute = _call(
        toolkit, "coder_run_tests", command="pytest", targets=[str(workspace / "a.py")], **base
    )
    assert absolute["code"] == coder_module.CODE_WORKSPACE

    too_long = _call(
        toolkit, "coder_run_tests", command="pytest", targets=["a.py"], timeout=121, **base
    )
    assert too_long["code"] == coder_module.CODE_LIMIT


def test_container_run_requires_opt_in_pinned_image_and_approval(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = {
        "image": _PINNED_IMAGE,
        "command": ["echo", "ok"],
        "workspace_root": str(workspace),
        "approval": _APPROVAL,
    }
    blocked = _call(toolkit, "coder_container_run", **base)
    assert blocked["code"] == coder_module.CODE_CONTAINER

    monkeypatch.setenv(coder_module.CONTAINER_ENV, "1")
    unpinned = _call(toolkit, "coder_container_run", **{**base, "image": "alpine:latest"})
    assert unpinned["code"] == coder_module.CODE_CONTAINER

    no_approval = _call(toolkit, "coder_container_run", **{**base, "approval": "no"})
    assert no_approval["code"] == coder_module.CODE_APPROVAL


def test_container_run_success_delegates_to_sandbox(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.coder.container_sandbox as sandbox_module

    monkeypatch.setenv(coder_module.CONTAINER_ENV, "1")
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], root: Path, **kwargs: Any) -> dict[str, Any]:
        seen["command"] = command
        seen["kwargs"] = kwargs
        return {"ok": True, "exit_code": 0}

    monkeypatch.setattr(sandbox_module, "run_in_container", fake_run)
    outcome = _call(
        toolkit,
        "coder_container_run",
        image=_PINNED_IMAGE,
        command=["echo", "ok"],
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )

    assert outcome["ok"] is True and outcome["mode"] == "container_sandbox"
    assert seen["command"] == ["echo", "ok"]
    assert seen["kwargs"]["approved"] is True
    assert seen["kwargs"]["image"] == _PINNED_IMAGE


def test_shared_audit_log_receives_every_call(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = CoderAuditLog()
    toolkit = build_coder_toolkit(workspace, audit=shared)
    monkeypatch.delenv(DEV_TOOLS_ENV, raising=False)

    _call(toolkit, "coder_plan_preview", plan=_create_plan())
    _call(
        toolkit,
        "coder_apply_plan",
        plan=_create_plan(),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )

    assert len(shared.events) == 2
    assert [event.tool for event in shared.events] == [
        "coder_plan_preview",
        "coder_apply_plan",
    ]
    assert shared.events[1].ok is False
    assert shared.events[1].error_code == coder_module.CODE_DISABLED


def _edit_plan(file: str, find: str, patch: str) -> dict[str, Any]:
    return {
        "goal": "edit a file",
        "defects": [],
        "steps": [
            {
                "file": file,
                "action": "edit",
                "reason": "apply the reviewed change",
                "patch_hint": patch,
                "risk": "low",
                "find": find,
            }
        ],
        "tests_to_run": ["pytest"],
    }


def _delete_plan(file: str) -> dict[str, Any]:
    return {
        "goal": "delete a file",
        "defects": [],
        "steps": [
            {
                "file": file,
                "action": "delete",
                "reason": "remove obsolete content",
                "patch_hint": "",
                "risk": "low",
                "find": "",
            }
        ],
        "tests_to_run": ["pytest"],
    }


def test_direct_safe_target_refusals(workspace: Path, toolkit: Any) -> None:
    for raw in (None, "", "bad\x00name", "-flag", ".ssh/config"):
        with pytest.raises(coder_module.CoderToolError) as exc:
            coder_module._safe_target(workspace, raw)
        assert exc.value.code == coder_module.CODE_WORKSPACE

    target, relative = coder_module._safe_target(workspace, "a/b.txt")
    assert target == workspace / "a" / "b.txt"
    assert relative == "a/b.txt"


def test_plan_shape_validation_and_file_cap(workspace: Path, toolkit: Any) -> None:
    bad_shape = _call(toolkit, "coder_plan_preview", plan=["not", "an", "object"])
    assert bad_shape["code"] == coder_module.CODE_PLAN

    invalid = _create_plan()
    invalid["goal"] = ""
    no_goal = _call(toolkit, "coder_plan_preview", plan=invalid)
    assert no_goal["code"] == coder_module.CODE_PLAN

    many = {
        "goal": "many files",
        "defects": [],
        "steps": [
            {
                "file": f"f{index}.txt",
                "action": "create",
                "reason": "bulk",
                "patch_hint": "x",
                "risk": "low",
                "find": "",
            }
            for index in range(coder_module.MAX_FILES + 1)
        ],
        "tests_to_run": ["pytest"],
    }
    capped = _call(toolkit, "coder_plan_preview", plan=many)
    assert capped["code"] == coder_module.CODE_LIMIT


def test_unsupported_plan_action_is_refused_directly(workspace: Path) -> None:
    from src.coder.plan import plan_from_json

    plan = plan_from_json(
        {
            "goal": "rename",
            "defects": [],
            "steps": [
                {
                    "file": "a.txt",
                    "action": "rename",
                    "reason": "not allowed",
                    "patch_hint": "x",
                    "risk": "low",
                    "find": "",
                }
            ],
            "tests_to_run": ["pytest"],
        }
    )
    with pytest.raises(coder_module.CoderToolError) as exc:
        coder_module._plan_changes(workspace, plan)
    assert exc.value.code == coder_module.CODE_PLAN


def test_edit_and_delete_plans_apply(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    (workspace / "edit.txt").write_text("before\n", encoding="utf-8")
    edited = _call(
        toolkit,
        "coder_apply_plan",
        plan=_edit_plan("edit.txt", "before", "after"),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert edited["ok"] is True
    assert (workspace / "edit.txt").read_text(encoding="utf-8") == "after\n"

    (workspace / "old.txt").write_text("obsolete\n", encoding="utf-8")
    deleted = _call(
        toolkit,
        "coder_apply_plan",
        plan=_delete_plan("old.txt"),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert deleted["ok"] is True
    assert not (workspace / "old.txt").exists()


def test_plan_change_preconditions(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    base = {"workspace_root": str(workspace), "approval": _APPROVAL}

    (workspace / "exists.txt").write_text("present\n", encoding="utf-8")
    exists = _call(toolkit, "coder_apply_plan", plan=_create_plan("exists.txt"), **base)
    assert exists["code"] == coder_module.CODE_PLAN

    missing_edit = _call(
        toolkit, "coder_apply_plan", plan=_edit_plan("missing.txt", "a", "b"), **base
    )
    assert missing_edit["code"] == coder_module.CODE_PLAN

    (workspace / "twice.txt").write_text("x x\n", encoding="utf-8")
    twice = _call(toolkit, "coder_apply_plan", plan=_edit_plan("twice.txt", "x", "y"), **base)
    assert twice["code"] == coder_module.CODE_PLAN

    missing_delete = _call(toolkit, "coder_apply_plan", plan=_delete_plan("gone.txt"), **base)
    assert missing_delete["code"] == coder_module.CODE_PLAN

    link = workspace / "link.txt"
    link.symlink_to(workspace.parent / "outside.txt")
    symlink = _call(toolkit, "coder_apply_plan", plan=_create_plan("link.txt"), **base)
    assert symlink["code"] == coder_module.CODE_WORKSPACE

    syntax = _call(toolkit, "coder_apply_plan", plan=_create_plan("bad.py", "def broken("), **base)
    assert syntax["code"] == coder_module.CODE_PLAN


def test_total_byte_cap_is_enforced(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    monkeypatch.setattr(coder_module, "MAX_TOTAL_BYTES", 4)
    outcome = _call(
        toolkit,
        "coder_apply_plan",
        plan=_create_plan(content="abcdef"),
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outcome["code"] == coder_module.CODE_LIMIT
    assert not (workspace / "notes.txt").exists()


def test_diff_output_cap_is_enforced(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coder_module, "MAX_OUTPUT_BYTES", 4)
    outcome = _call(toolkit, "coder_plan_preview", plan=_create_plan())
    assert outcome["code"] == coder_module.CODE_LIMIT


def test_atomic_write_cleans_temporary_file_on_failure(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(src: str, dst: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(coder_module.os, "replace", fail_replace)
    with pytest.raises(OSError):
        coder_module._atomic_write(workspace / "x.txt", "data")
    assert not list(workspace.glob(".coder-tmp-*"))


def test_apply_plan_rolls_back_created_file(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    original = coder_module._atomic_write
    calls = {"count": 0}

    def fail_second(target: Path, content: str) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("boom")
        original(target, content)

    monkeypatch.setattr(coder_module, "_atomic_write", fail_second)
    plan = {
        "goal": "two creates",
        "defects": [],
        "steps": [
            {
                "file": name,
                "action": "create",
                "reason": "bulk",
                "patch_hint": "new",
                "risk": "low",
                "find": "",
            }
            for name in ("first.txt", "second.txt")
        ],
        "tests_to_run": ["pytest"],
    }
    outcome = _call(
        toolkit,
        "coder_apply_plan",
        plan=plan,
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outcome["code"] == coder_module.CODE_RUNTIME
    assert not (workspace / "first.txt").exists()
    assert not (workspace / "second.txt").exists()


def test_apply_plan_rolls_back_edited_file(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    (workspace / "a.txt").write_text("a\n", encoding="utf-8")
    (workspace / "b.txt").write_text("b\n", encoding="utf-8")
    original = coder_module._atomic_write
    calls = {"count": 0}

    def fail_second(target: Path, content: str) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("boom")
        original(target, content)

    monkeypatch.setattr(coder_module, "_atomic_write", fail_second)
    plan = {
        "goal": "two edits",
        "defects": [],
        "steps": [
            {
                "file": name,
                "action": "edit",
                "reason": "bulk",
                "patch_hint": name.upper() + "\n",
                "risk": "low",
                "find": name[0] + "\n",
            }
            for name in ("a.txt", "b.txt")
        ],
        "tests_to_run": ["pytest"],
    }
    outcome = _call(
        toolkit,
        "coder_apply_plan",
        plan=plan,
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outcome["code"] == coder_module.CODE_RUNTIME
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert (workspace / "b.txt").read_text(encoding="utf-8") == "b\n"


def test_bounded_command_success_and_nonzero_exit(workspace: Path) -> None:
    good = coder_module._bounded_command([sys.executable, "-c", "print('ok')"], workspace, 10)
    assert good["ok"] is True and good["exit_code"] == 0
    assert "ok" in good["stdout"]

    bad = coder_module._bounded_command(
        [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)"],
        workspace,
        10,
    )
    assert bad["ok"] is False and bad["exit_code"] == 3
    assert "bad" in bad["stderr"]


def test_bounded_command_timeout(workspace: Path) -> None:
    with pytest.raises(coder_module.CoderToolError) as exc:
        coder_module._bounded_command(
            [sys.executable, "-c", "import time; time.sleep(3)"], workspace, 1
        )
    assert exc.value.code == coder_module.CODE_LIMIT


def test_bounded_command_output_cap(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coder_module, "MAX_OUTPUT_BYTES", 2)
    with pytest.raises(coder_module.CoderToolError) as exc:
        coder_module._bounded_command([sys.executable, "-c", "print('abcdef')"], workspace, 10)
    assert exc.value.code == coder_module.CODE_LIMIT


def test_bounded_command_start_failure(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("no exec")

    monkeypatch.setattr(coder_module.subprocess, "Popen", fail)
    with pytest.raises(coder_module.CoderToolError) as exc:
        coder_module._bounded_command([sys.executable, "-c", "pass"], workspace, 10)
    assert exc.value.code == coder_module.CODE_RUNTIME


def test_unknown_tool_and_generic_failure_are_content_free(
    toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    unknown = _call(toolkit, "does_not_exist")
    assert unknown["code"] == coder_module.CODE_RUNTIME
    assert toolkit.audit.events[-1].tool == "does_not_exist"
    assert toolkit.audit.events[-1].permission_mode == "unknown"

    def explode(arguments: Mapping[str, Any]) -> dict[str, Any]:
        raise ValueError("secret must not leak")

    monkeypatch.setattr(toolkit, "plan_preview", explode)
    failed = _call(toolkit, "coder_plan_preview", plan=_create_plan())
    assert failed == {"code": coder_module.CODE_RUNTIME, "message": "coder tool failed"}
    assert "secret must not leak" not in json.dumps(failed)


@pytest.mark.parametrize(
    ("command", "tail"),
    [
        ("pytest", ["-m", "pytest", "-q", "--no-header"]),
        ("mypy", ["-m", "mypy"]),
    ],
)
def test_run_tests_prefixes_are_bounded(
    workspace: Path,
    toolkit: Any,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    tail: list[str],
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    (workspace / "a.py").write_text("print(1)\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], root: Path, timeout: Any) -> dict[str, Any]:
        seen["argv"] = argv
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(coder_module, "_bounded_command", fake_run)
    outcome = _call(
        toolkit,
        "coder_run_tests",
        command=command,
        targets=["a.py"],
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outcome["ok"] is True
    assert seen["argv"] == [sys.executable, *tail, "a.py"]


def test_run_tests_refuses_missing_scope_and_bad_targets(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    (workspace / "a.py").write_text("print(1)\n", encoding="utf-8")

    no_scope = _call(
        toolkit, "coder_run_tests", command="pytest", targets=["a.py"], approval=_APPROVAL
    )
    assert no_scope["code"] == coder_module.CODE_WORKSPACE

    wrong_scope = _call(
        toolkit,
        "coder_run_tests",
        command="pytest",
        targets=["a.py"],
        workspace_root=str(workspace.parent),
        approval=_APPROVAL,
    )
    assert wrong_scope["code"] == coder_module.CODE_WORKSPACE

    base = {"workspace_root": str(workspace), "approval": _APPROVAL}
    empty = _call(toolkit, "coder_run_tests", command="pytest", targets=[], **base)
    assert empty["code"] == coder_module.CODE_COMMAND

    missing = _call(toolkit, "coder_run_tests", command="pytest", targets=["gone.py"], **base)
    assert missing["code"] == coder_module.CODE_COMMAND

    boolean_timeout = _call(
        toolkit,
        "coder_run_tests",
        command="pytest",
        targets=["a.py"],
        timeout=True,
        **base,
    )
    assert boolean_timeout["code"] == coder_module.CODE_LIMIT

    monkeypatch.setattr(coder_module, "MAX_COMMAND_PARTS", 4)
    too_many_parts = _call(toolkit, "coder_run_tests", command="pytest", targets=["a.py"], **base)
    assert too_many_parts["code"] == coder_module.CODE_LIMIT


def test_container_run_bad_command_and_sandbox_failure(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.coder.container_sandbox as sandbox_module

    monkeypatch.setenv(coder_module.CONTAINER_ENV, "1")
    base = {
        "image": _PINNED_IMAGE,
        "workspace_root": str(workspace),
        "approval": _APPROVAL,
    }
    no_scope = _call(toolkit, "coder_container_run", command=["echo", "ok"], approval=_APPROVAL)
    assert no_scope["code"] == coder_module.CODE_WORKSPACE

    empty_command = _call(toolkit, "coder_container_run", command=[], **base)
    assert empty_command["code"] == coder_module.CODE_COMMAND

    string_command = _call(toolkit, "coder_container_run", command="echo ok", **base)
    assert string_command["code"] == coder_module.CODE_COMMAND

    bad_part = _call(toolkit, "coder_container_run", command=["echo", ""], **base)
    assert bad_part["code"] == coder_module.CODE_COMMAND

    monkeypatch.setattr(coder_module, "MAX_COMMAND_PARTS", 3)
    oversized = _call(
        toolkit,
        "coder_container_run",
        command=["echo", "a", "b", "c"],
        **base,
    )
    assert oversized["code"] == coder_module.CODE_COMMAND

    def blocked(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise sandbox_module.ContainerSandboxError("blocked")

    monkeypatch.setattr(sandbox_module, "run_in_container", blocked)
    refused = _call(toolkit, "coder_container_run", command=["echo", "ok"], **base)
    assert refused["code"] == coder_module.CODE_CONTAINER


def test_container_run_reports_failed_exit(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.coder.container_sandbox as sandbox_module

    monkeypatch.setenv(coder_module.CONTAINER_ENV, "1")

    def failed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": False, "exit_code": 7}

    monkeypatch.setattr(sandbox_module, "run_in_container", failed)
    outcome = _call(
        toolkit,
        "coder_container_run",
        image=_PINNED_IMAGE,
        command=["echo", "ok"],
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outcome == {"ok": False, "mode": "container_sandbox", "exit_code": 7}


def test_atomic_write_cleanup_survives_unlink_failure(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(src: str, dst: str) -> None:
        raise OSError("replace failed")

    def fail_unlink(path: str) -> None:
        raise OSError("unlink failed")

    monkeypatch.setattr(coder_module.os, "replace", fail_replace)
    monkeypatch.setattr(coder_module.os, "unlink", fail_unlink)
    with pytest.raises(OSError):
        coder_module._atomic_write(workspace / "x.txt", "data")


def test_bounded_command_ignores_broken_pipe_drain(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    class BrokenPipe:
        def read(self, size: int) -> bytes:
            raise OSError("pipe closed")

        def close(self) -> None:
            raise OSError("close failed")

    fake = types.SimpleNamespace(
        pid=1,
        stdout=BrokenPipe(),
        stderr=BrokenPipe(),
        returncode=0,
        wait=lambda timeout=None: 0,
    )
    monkeypatch.setattr(coder_module.subprocess, "Popen", lambda *a, **k: fake)
    outcome = coder_module._bounded_command(["ignored"], workspace, 10)
    assert outcome == {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}


def test_bounded_command_timeout_killpg_fallback(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_killpg(pgid: int, sig: int) -> None:
        raise ProcessLookupError("no group")

    monkeypatch.setattr(coder_module.os, "killpg", fail_killpg)
    with pytest.raises(coder_module.CoderToolError) as exc:
        coder_module._bounded_command(
            [sys.executable, "-c", "import time; time.sleep(2)"], workspace, 1
        )
    assert exc.value.code == coder_module.CODE_LIMIT


def test_apply_plan_returns_runtime_error_even_if_rollback_fails(
    workspace: Path, toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DEV_TOOLS_ENV, "1")
    original = coder_module._atomic_write
    calls = {"count": 0}

    def fail_after_first(target: Path, content: str) -> None:
        calls["count"] += 1
        if calls["count"] > 1:
            raise OSError("write failed")
        original(target, content)

    monkeypatch.setattr(coder_module, "_atomic_write", fail_after_first)
    plan = {
        "goal": "two creates",
        "defects": [],
        "steps": [
            {
                "file": name,
                "action": "create",
                "reason": "bulk",
                "patch_hint": "new",
                "risk": "low",
                "find": "",
            }
            for name in ("first.txt", "second.txt")
        ],
        "tests_to_run": ["pytest"],
    }
    outcome = _call(
        toolkit,
        "coder_apply_plan",
        plan=plan,
        workspace_root=str(workspace),
        approval=_APPROVAL,
    )
    assert outcome["code"] == coder_module.CODE_RUNTIME
