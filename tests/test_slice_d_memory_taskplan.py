"""Slice D: bounded project memory and task-plan tracking for Zyko.

All tests are local and deterministic; no subprocess and no mcp-hub access.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.mcp.client import content_text
from src.mcp.framework import build_framework_server
from src.mcp.memory_tools import (
    CODE_APPROVAL,
    CODE_CONFLICT,
    CODE_DISABLED,
    CODE_INPUT,
    CODE_LIMIT,
    CODE_RUNTIME,
    CODE_SCOPE,
    CODE_SECRET,
    CODE_WORKSPACE,
    DEFAULT_DB_PATH,
    MAX_ARGUMENT_COUNT,
    MAX_PLAN_BYTES,
    MAX_PLAN_STEPS,
    MAX_STEP_TEXT_CHARS,
    MAX_VALUE_CHARS,
    MEMORY_WRITES_ENV,
    MEMORY_TOOL_NAMES,
    MemoryAuditLog,
    MemoryToolError,
    TaskPlanStore,
    build_memory_toolkit,
    memory_tool_schemas,
)

SCOPE: dict[str, str] = {"project": "zyko", "session": "s1"}
APPROVAL: dict[str, str] = {"approval": "approve"}
_AUDIT_KEYS = {"tool", "permission_mode", "ok", "duration_ms", "chars", "error_code"}


@pytest.fixture
def toolkit(tmp_path: Path) -> Any:
    instance = build_memory_toolkit(tmp_path)
    yield instance
    instance.manager.close()


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MEMORY_WRITES_ENV, "1")


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    return json.loads(content_text(result))


def _record(
    toolkit: Any, *, text: str = "خطة نشر المشروع", key: str = "plan_note"
) -> dict[str, Any]:
    return _payload(
        toolkit.call("memory_record", {**SCOPE, "key": key, "content": text, **APPROVAL})
    )


# -- registration and schemas ------------------------------------------------
def test_memory_tools_are_opt_in(tmp_path: Path) -> None:
    default_server = build_framework_server(root=tmp_path, include_agents=False)
    assert not (MEMORY_TOOL_NAMES & set(default_server.tool_names()))
    assert not (tmp_path / DEFAULT_DB_PATH).exists()
    enabled = build_framework_server(root=tmp_path, include_agents=False, include_memory_tools=True)
    assert MEMORY_TOOL_NAMES <= set(enabled.tool_names())


def test_framework_handler_is_audited(tmp_path: Path) -> None:
    audit = MemoryAuditLog()
    server = build_framework_server(
        root=tmp_path,
        include_agents=False,
        include_memory_tools=True,
        memory_audit=audit,
    )
    result = server.call_tool("task_plan_get", dict(SCOPE))
    assert result["isError"] is False
    assert _payload(result)["version"] == 0
    assert len(audit.events) == 1
    assert audit.events[0].tool == "task_plan_get"


def test_schemas_declare_bounds_and_write_gate() -> None:
    schemas = memory_tool_schemas()
    assert set(schemas) == MEMORY_TOOL_NAMES
    assert schemas["memory_recall"]["properties"]["limit"]["maximum"] == 8
    assert schemas["memory_record"]["properties"]["content"]["maxLength"] == 4096
    assert "approval" in schemas["memory_record"]["required"]
    assert "approval" in schemas["task_plan_update"]["required"]
    assert schemas["task_plan_update"]["properties"]["steps"]["maxItems"] == MAX_PLAN_STEPS
    assert set(
        schemas["task_plan_update"]["properties"]["steps"]["items"]["properties"]["status"]["enum"]
    ) == {
        "done",
        "doing",
        "todo",
    }


def test_framework_respects_custom_db_path(tmp_path: Path) -> None:
    server = build_framework_server(
        root=tmp_path,
        include_agents=False,
        include_memory_tools=True,
        memory_db_path="data/mem.sqlite",
    )
    result = server.call_tool("task_plan_get", dict(SCOPE))
    assert result["isError"] is False
    assert (tmp_path / "data" / "mem.sqlite").exists()


# -- audit discipline --------------------------------------------------------
def test_one_content_free_event_per_call(toolkit: Any) -> None:
    toolkit.call("task_plan_get", dict(SCOPE))
    toolkit.call("memory_recall", {**SCOPE, "query": "missing"})
    assert len(toolkit.audit.events) == 2
    for event in toolkit.audit.events:
        record = event.to_dict()
        assert set(record) == _AUDIT_KEYS
        assert "zyko" not in json.dumps(record)
        assert "s1" not in json.dumps(record)
        assert record["permission_mode"] == "read_only"


def test_write_failure_is_audited_once_without_values(toolkit: Any, writes: None) -> None:
    result = _payload(
        toolkit.call("memory_record", {**SCOPE, "key": "k", "content": "secret", "approval": "no"})
    )
    assert result["code"] == CODE_APPROVAL
    assert len(toolkit.audit.events) == 1
    event = toolkit.audit.events[0].to_dict()
    assert event["ok"] is False
    assert event["error_code"] == CODE_APPROVAL
    assert "secret" not in json.dumps(event)


def test_unknown_tool_and_oversized_arguments(toolkit: Any) -> None:
    assert _payload(toolkit.call("memory_delete", {}))["code"] == CODE_INPUT
    assert _payload(toolkit.call("task_plan_get", {"x": "y" * 40_000}))["code"] == CODE_LIMIT
    assert (
        _payload(
            toolkit.call("task_plan_get", {f"k{i}": 1 for i in range(MAX_ARGUMENT_COUNT + 1)})
        )["code"]
        == CODE_LIMIT
    )
    assert len(toolkit.audit.events) == 3


def test_on_audit_hook(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    toolkit = build_memory_toolkit(tmp_path, on_audit=lambda event: seen.append(event.to_dict()))
    toolkit.call("task_plan_get", dict(SCOPE))
    assert len(seen) == 1
    assert seen[0]["tool"] == "task_plan_get"


# -- scope and path guards ---------------------------------------------------
@pytest.mark.parametrize(
    "project,session",
    [
        ("", "s1"),
        ("zyko", ""),
        (123, "s1"),
        ("zyko", "session١"),
        ("zyko", "x" * 129),
        ("../zyko", "s1"),
        ("zyko", None),
    ],
)
def test_scope_validation(toolkit: Any, project: Any, session: Any) -> None:
    result = _payload(toolkit.call("task_plan_get", {"project": project, "session": session}))
    assert result["code"] == CODE_SCOPE
    assert toolkit.audit.events[-1].error_code == CODE_SCOPE


@pytest.mark.parametrize(
    "raw",
    [
        "../escape.db",
        "/tmp/escape.db",
        ".ssh/memory.db",
        ".git/memory.db",
        ".env",
        "creds.pem",
        "a" * 513,
        7,
    ],
)
def test_db_path_is_confined(toolkit: Any, tmp_path: Path, raw: Any) -> None:
    with pytest.raises(MemoryToolError) as excinfo:
        build_memory_toolkit(tmp_path, db_path=raw)
    assert excinfo.value.code == CODE_WORKSPACE
    assert not (tmp_path / "escape.db").exists()


def test_db_path_refuses_symlink(tmp_path: Path) -> None:
    (tmp_path / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(MemoryToolError) as excinfo:
        build_memory_toolkit(tmp_path, db_path="linked/memory.db")
    assert excinfo.value.code == CODE_WORKSPACE


def test_db_path_inside_workspace(tmp_path: Path) -> None:
    toolkit = build_memory_toolkit(tmp_path, db_path="state/memory.sqlite")
    assert toolkit.manager.path == str(tmp_path / "state" / "memory.sqlite")


def test_existing_manager_is_reused(tmp_path: Path) -> None:
    from src.memory.manager import MemoryManager

    manager = MemoryManager(tmp_path / "custom.sqlite")
    toolkit = build_memory_toolkit(tmp_path, manager=manager)
    assert toolkit.manager is manager
    toolkit.manager.close()


# -- bounded memory ----------------------------------------------------------
def test_record_requires_gate_and_approval(toolkit: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    args = {**SCOPE, "key": "k", "content": "plain note"}
    monkeypatch.delenv(MEMORY_WRITES_ENV, raising=False)
    assert _payload(toolkit.call("memory_record", {**args, **APPROVAL}))["code"] == CODE_DISABLED
    monkeypatch.setenv(MEMORY_WRITES_ENV, "1")
    assert _payload(toolkit.call("memory_record", args))["code"] == CODE_APPROVAL
    monkeypatch.setenv(MEMORY_WRITES_ENV, "true")
    assert _payload(toolkit.call("memory_record", {**args, **APPROVAL}))["code"] == CODE_DISABLED
    assert toolkit.manager.semantic.count() == 0


@pytest.mark.parametrize(
    "content",
    [
        "ghp_" + "a" * 20,
        "sk-proj-" + "b" * 20,
        "AKIA" + "C" * 16,
        "Bearer " + "d" * 20,
        "password: " + "e" * 12,
        "-----BEGIN " + "RSA PRIVATE KEY-----",
        "eyJ"
        + "hbGciOiJIUzI1NiJ9"
        + "."
        + "eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        + "."
        + "abcdefghijklmnop",
    ],
)
def test_secret_content_is_refused(toolkit: Any, writes: None, content: str) -> None:
    result = _payload(
        toolkit.call("memory_record", {**SCOPE, "key": "k", "content": content, **APPROVAL})
    )
    assert result["code"] == CODE_SECRET
    assert toolkit.manager.semantic.count() == 0


@pytest.mark.parametrize(
    "content,key,code",
    [
        ("", "k", CODE_INPUT),
        ("   ", "k", CODE_INPUT),
        ("bad\x00content", "k", CODE_INPUT),
        ("x" * 5000, "k", CODE_LIMIT),
        ("note", "k١", CODE_INPUT),
        ("note", "", CODE_INPUT),
    ],
)
def test_record_input_limits(toolkit: Any, writes: None, content: str, key: str, code: int) -> None:
    result = _payload(
        toolkit.call("memory_record", {**SCOPE, "key": key, "content": content, **APPROVAL})
    )
    assert result["code"] == code


def test_record_and_recall_roundtrip(toolkit: Any, writes: None) -> None:
    assert _record(toolkit, text="نشر المشروع اليوم")[ok_key()] is True
    result = _payload(toolkit.call("memory_recall", {**SCOPE, "query": "نشر"}))
    assert result["count"] == 1
    assert result["results"][0]["text"] == "نشر المشروع اليوم"
    assert result["mode"] == "read_only"
    other = _payload(toolkit.call("memory_recall", {**SCOPE, "session": "s2", "query": "نشر"}))
    assert other["count"] == 0


def test_recall_limits_and_query_validation(toolkit: Any) -> None:
    assert _payload(toolkit.call("memory_recall", {**SCOPE, "query": "  "}))["code"] == CODE_INPUT
    assert (
        _payload(toolkit.call("memory_recall", {**SCOPE, "query": "x" * 600}))["code"] == CODE_LIMIT
    )
    for limit in (0, 9, "3", True):
        result = _payload(toolkit.call("memory_recall", {**SCOPE, "query": "note", "limit": limit}))
        assert result["code"] == CODE_LIMIT


def test_recall_redacts_and_truncates(toolkit: Any) -> None:
    value = "ghp_" + "z" * 20 + " " + "و" * 900
    toolkit.manager.semantic.remember("leaky", value, subject="zyko/s1", source="seed")
    result = _payload(toolkit.call("memory_recall", {**SCOPE, "query": "leaky"}))
    assert result["count"] == 1
    text = result["results"][0]["text"]
    assert "[redacted]" in text
    assert len(text) <= MAX_VALUE_CHARS
    assert "z" * 20 not in text
    assert all(key not in json.dumps(toolkit.audit.events[0].to_dict()) for key in ("leaky", value))


def test_recall_result_cap_is_bounded(toolkit: Any, writes: None) -> None:
    for index in range(10):
        _record(toolkit, text=f"note {index}", key=f"k{index}")
    result = _payload(toolkit.call("memory_recall", {**SCOPE, "query": "note", "limit": 8}))
    assert result["count"] == 8


# -- task plans --------------------------------------------------------------
def test_plan_default_and_scope_isolation(toolkit: Any, writes: None) -> None:
    empty = _payload(toolkit.call("task_plan_get", dict(SCOPE)))
    assert empty == {
        "ok": True,
        "mode": "read_only",
        "version": 0,
        "steps": [],
        "summary": {"done": 0, "doing": 0, "todo": 0},
    }
    result = _payload(toolkit.call("task_plan_get", {**SCOPE, "session": "s2"}))
    assert result["version"] == 0


def test_plan_update_requires_gate_and_approval(
    toolkit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = [{"id": "a", "text": "خطوة أولى", "status": "doing"}]
    args = {**SCOPE, "steps": steps}
    monkeypatch.delenv(MEMORY_WRITES_ENV, raising=False)
    assert _payload(toolkit.call("task_plan_update", {**args, **APPROVAL}))["code"] == CODE_DISABLED
    monkeypatch.setenv(MEMORY_WRITES_ENV, "1")
    assert _payload(toolkit.call("task_plan_update", args))["code"] == CODE_APPROVAL


def test_plan_roundtrip_and_version_guard(toolkit: Any, writes: None) -> None:
    steps = [
        {"id": "a", "text": "تصميم", "status": "done"},
        {"id": "b", "text": "تنفيذ", "status": "doing"},
        {"id": "c", "text": "اختبار", "status": "todo"},
    ]
    first = _payload(toolkit.call("task_plan_update", {**SCOPE, "steps": steps, **APPROVAL}))
    assert first["version"] == 1
    assert first["summary"] == {"done": 1, "doing": 1, "todo": 1}
    current = _payload(toolkit.call("task_plan_get", dict(SCOPE)))
    assert current["version"] == 1
    assert [step["text"] for step in current["steps"]] == ["تصميم", "تنفيذ", "اختبار"]
    conflict = _payload(
        toolkit.call(
            "task_plan_update", {**SCOPE, "steps": steps, "expected_version": 99, **APPROVAL}
        )
    )
    assert conflict["code"] == CODE_CONFLICT
    second = _payload(
        toolkit.call(
            "task_plan_update", {**SCOPE, "steps": steps, "expected_version": 1, **APPROVAL}
        )
    )
    assert second["version"] == 2
    assert _payload(toolkit.call("task_plan_get", dict(SCOPE)))["version"] == 2


@pytest.mark.parametrize(
    "steps,code",
    [
        ([], CODE_LIMIT),
        ([{"id": f"s{i}", "text": "x", "status": "todo"} for i in range(33)], CODE_LIMIT),
        (
            [
                {"id": "a", "text": "x", "status": "todo"},
                {"id": "a", "text": "y", "status": "todo"},
            ],
            CODE_INPUT,
        ),
        ([{"id": "a", "text": "x", "status": "pending"}], CODE_INPUT),
        (
            [
                {"id": "a", "text": "x", "status": "doing"},
                {"id": "b", "text": "y", "status": "doing"},
            ],
            CODE_INPUT,
        ),
        ([{"id": "a", "text": "x" * (MAX_STEP_TEXT_CHARS + 1), "status": "todo"}], CODE_LIMIT),
        ([{"id": "a", "text": "password: " + "q" * 12, "status": "todo"}], CODE_SECRET),
        ([{"id": "a", "text": "bad\x00text", "status": "todo"}], CODE_INPUT),
        (["not-a-step"], CODE_INPUT),
        ([{"id": "١", "text": "x", "status": "todo"}], CODE_INPUT),
    ],
)
def test_plan_step_validation(toolkit: Any, writes: None, steps: Any, code: int) -> None:
    result = _payload(toolkit.call("task_plan_update", {**SCOPE, "steps": steps, **APPROVAL}))
    assert result["code"] == code


def test_plan_serialized_size_cap(toolkit: Any, writes: None) -> None:
    steps = [
        {"id": f"step{i}", "text": "x" * MAX_STEP_TEXT_CHARS, "status": "todo"}
        for i in range(MAX_PLAN_STEPS)
    ]
    serialized = json.dumps({"steps": steps}, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized) > MAX_PLAN_BYTES
    result = _payload(toolkit.call("task_plan_update", {**SCOPE, "steps": steps, **APPROVAL}))
    assert result["code"] == CODE_LIMIT


def test_plan_version_limit(toolkit: Any, writes: None) -> None:
    from src.mcp.memory_tools import MAX_VERSION

    store = TaskPlanStore(toolkit.manager.connection)
    store.update(("zyko", "s1"), [{"id": "a", "text": "x", "status": "todo"}])
    toolkit.manager.connection.execute(
        "UPDATE task_plans SET version = ? WHERE project = ? AND session = ?",
        (MAX_VERSION, "zyko", "s1"),
    )
    toolkit.manager.connection.commit()
    result = _payload(
        toolkit.call(
            "task_plan_update",
            {**SCOPE, "steps": [{"id": "a", "text": "x", "status": "todo"}], **APPROVAL},
        )
    )
    assert result["code"] == CODE_LIMIT


def test_plan_get_redacts_stored_secret(toolkit: Any) -> None:
    store = TaskPlanStore(toolkit.manager.connection)
    store.update(
        ("zyko", "s1"),
        [{"id": "a", "text": "ghp_" + "q" * 20, "status": "todo"}],
    )
    result = _payload(toolkit.call("task_plan_get", dict(SCOPE)))
    assert result["steps"][0]["text"] == "[redacted]"


def test_invalid_expected_version(toolkit: Any, writes: None) -> None:
    result = _payload(
        toolkit.call(
            "task_plan_update",
            {
                **SCOPE,
                "steps": [{"id": "a", "text": "x", "status": "todo"}],
                "expected_version": True,
                **APPROVAL,
            },
        )
    )
    assert result["code"] == CODE_INPUT


def test_corrupt_plan_is_runtime_error_without_leaking(toolkit: Any) -> None:
    toolkit.manager.connection.execute(
        """
        INSERT INTO task_plans (project, session, version, updated_ts, updated_iso, plan_json)
        VALUES ('zyko', 's1', 1, 0, 'now', '{broken')
        """
    )
    toolkit.manager.connection.commit()
    result = _payload(toolkit.call("task_plan_get", dict(SCOPE)))
    assert result["code"] == CODE_RUNTIME
    assert len(toolkit.audit.events) == 1
    assert toolkit.audit.events[0].error_code == CODE_RUNTIME


def ok_key() -> str:
    """The success flag used by the memory record helper."""
    return "ok"
