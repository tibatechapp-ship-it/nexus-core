"""Tests for the opt-in, dev-bounded coder MCP tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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
