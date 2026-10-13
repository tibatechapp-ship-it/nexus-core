"""Tests for src.mcp.framework — the nexus-core framework-surface MCP server."""

from __future__ import annotations

import importlib
import json

import pytest

from src.core.types import AgentResult
from src.mcp import framework as fw
from src.mcp.client import InProcessClient

_EXPECTED_LOCAL = {"read_file", "list_dir", "grep"}
_EXPECTED_SECURITY = {"security_scan", "security_scan_text"}
_EXPECTED_GIT = {"git_status", "git_log", "git_branches", "git_diff", "git_show"}


def _git_repo(tmp_path):  # noqa: ANN001, ANN202
    """Initialise a tiny git repo in ``tmp_path`` (skip if git is absent)."""
    import subprocess

    if not fw_available():
        pytest.skip("git not installed")
    env = ["-c", "user.email=t@e.st", "-c", "user.name=Test"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", *env, "commit", "-qm", "first post"], cwd=tmp_path, check=True)
    return tmp_path


def fw_available() -> bool:  # noqa: ANN201
    from shutil import which

    return which("git") is not None



# ── assembly ──────────────────────────────────────────────────────────────
def test_build_framework_server_default(tmp_path):
    server = fw.build_framework_server(root=tmp_path)
    names = set(server.tool_names())
    agent_tools = {name for name in names if name.startswith("agent_")}
    assert len(agent_tools) == 20
    assert _EXPECTED_SECURITY <= names
    assert _EXPECTED_LOCAL <= names
    assert _EXPECTED_GIT <= names
    assert "agent_architect" in names
    assert server.name == "nexus-core"
    assert server.version == "1.5.0"


def test_build_framework_server_flags(tmp_path):
    only_agents = fw.build_framework_server(
        root=tmp_path, include_security=False, include_local_tools=False, include_git=False
    )
    assert all(name.startswith("agent_") for name in only_agents.tool_names())
    only_security = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_local_tools=False, include_git=False
    )
    assert set(only_security.tool_names()) == _EXPECTED_SECURITY
    only_local = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False, include_git=False
    )
    assert set(only_local.tool_names()) == _EXPECTED_LOCAL
    only_git = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False, include_local_tools=False
    )
    assert set(only_git.tool_names()) == _EXPECTED_GIT


def test_build_framework_server_custom_identity(tmp_path):
    server = fw.build_framework_server(root=tmp_path, name="custom", version="0.1")
    assert server.name == "custom"
    assert server.version == "0.1"
    assert server.instructions


def test_default_backend_is_echo():
    from src.core.backend import EchoBackend

    assert isinstance(fw._default_backend(), EchoBackend)


def test_agent_tools_use_injected_factory(tmp_path, monkeypatch):
    calls: list[str] = []

    class _StubAgent:
        name = "chooser"
        group = "core"
        description = "picks things"

        def run(self, task, *, context=""):  # noqa: ANN001, ANN202
            calls.append(task)
            return AgentResult(agent=self.name, ok=True, output=f"did:{task}")

    monkeypatch.setattr("src.agents.all_agents", lambda backend, **kw: [_StubAgent()])
    server = fw.build_framework_server(
        root=tmp_path, include_security=False, include_local_tools=False, include_git=False
    )
    assert server.tool_names() == ["agent_chooser"]
    result = server.call_tool("agent_chooser", {"task": "job", "context": "ctx"})
    assert result["isError"] is False
    assert result["content"][0]["text"] == "did:job"
    assert calls == ["job"]


def test_agent_handler_rejects_missing_task():
    class _Agent:
        def run(self, task, *, context=""):  # noqa: ANN001, ANN202
            raise AssertionError("must not run")

    handler = fw._make_agent_handler(_Agent())
    assert handler({})["isError"] is True
    assert handler({"task": "   "})["isError"] is True


def test_agent_handler_reports_failure():
    class _Agent:
        def run(self, task, *, context=""):  # noqa: ANN001, ANN202
            return AgentResult(agent="a", ok=False, error="nope")

    result = fw._make_agent_handler(_Agent())({"task": "x"})
    assert result["isError"] is True
    assert "nope" in result["content"][0]["text"]


def test_agent_handler_failure_without_message():
    class _Agent:
        def run(self, task, *, context=""):  # noqa: ANN001, ANN202
            return AgentResult(agent="a", ok=False)

    result = fw._make_agent_handler(_Agent())({"task": "x"})
    assert "agent run failed" in result["content"][0]["text"]


def test_agent_via_inprocess_client(tmp_path):
    client = InProcessClient(fw.build_framework_server(root=tmp_path))
    result = client.call_tool("agent_planner", {"task": "plan it"})
    assert result.startswith("echo:")


# ── security tools ────────────────────────────────────────────────────────
def test_security_scan_path(tmp_path):
    (tmp_path / "vuln.py").write_text("import hashlib\nhashlib.md5(b'x')\n", encoding="utf-8")
    client = InProcessClient(
        fw.build_framework_server(root=tmp_path, include_agents=False, include_local_tools=False)
    )
    report = json.loads(client.call_tool("security_scan", {"target": "vuln.py", "profile": "secrets"}))
    assert report["target"].endswith("vuln.py")
    assert "score" in report


def test_security_scan_escape_is_refused(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_local_tools=False
    )
    result = server.call_tool("security_scan", {"target": "../outside.py"})
    assert result["isError"] is True


def test_security_scan_missing_target(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_local_tools=False
    )
    result = server.call_tool("security_scan", {"target": "ghost.py"})
    assert result["isError"] is True
    assert "does not exist" in result["content"][0]["text"]


def test_security_scan_invalid_profile_falls_back(tmp_path):
    (tmp_path / "x.py").write_text("print('ok')\n", encoding="utf-8")
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_local_tools=False
    )
    result = server.call_tool("security_scan", {"target": "x.py", "profile": "does-not-exist"})
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["profile"] == "full"


def test_security_scan_text(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_local_tools=False
    )
    result = server.call_tool("security_scan_text", {"text": "password = 'hunter2'", "path": "a.py"})
    assert result["isError"] is False
    assert "findings" in result["content"][0]["text"]


def test_security_scan_text_requires_string(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_local_tools=False
    )
    result = server.call_tool("security_scan_text", {"text": 5})
    assert result["isError"] is True


# ── local tools ───────────────────────────────────────────────────────────
def test_local_tools_roundtrip(tmp_path):
    (tmp_path / "hello.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    client = InProcessClient(
        fw.build_framework_server(root=tmp_path, include_agents=False, include_security=False)
    )
    assert client.call_tool("read_file", {"path": "hello.txt"}) == "hello world\n"
    listing = client.call_tool("list_dir", {"path": "."})
    assert "hello.txt" in listing
    assert "world" in client.call_tool("grep", {"pattern": "world", "path": "."})


def test_read_file_without_path_is_error(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False
    )
    result = server.call_tool("read_file", {})
    assert result["isError"] is True


def test_local_tool_escape_is_refused(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False
    )
    result = server.call_tool("read_file", {"path": "../../etc/passwd"})
    assert result["isError"] is True


def test_local_tool_missing_file_is_error(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False
    )
    result = server.call_tool("list_dir", {"path": "nope"})
    assert result["isError"] is True


def test_confine(tmp_path):
    assert fw._confine(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt")
    with pytest.raises(ValueError):
        fw._confine(tmp_path, None)
    with pytest.raises(PermissionError):
        fw._confine(tmp_path, "../escape")


def test_scan_profile_defaults_and_valid(tmp_path):
    assert fw._scan_profile({}) == "full"
    assert fw._scan_profile({"profile": "secrets"}) == "secrets"
    assert fw._scan_profile({"profile": "bogus"}) == "full"


# ── git tools ─────────────────────────────────────────────────────────────
def test_git_tools_roundtrip(tmp_path):
    repo = _git_repo(tmp_path)
    client = InProcessClient(
        fw.build_framework_server(
            root=repo, include_agents=False, include_security=False, include_local_tools=False
        )
    )
    assert "##" in client.call_tool("git_status", {})
    assert "first post" in client.call_tool("git_log", {"limit": 5})
    assert client.call_tool("git_branches", {}).strip()
    assert "first post" in client.call_tool("git_show", {"ref": "HEAD", "stat_only": True})


def test_git_status_outside_repo_is_error(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False, include_local_tools=False
    )
    result = server.call_tool("git_status", {})
    assert result["isError"] is True


def test_git_show_requires_ref(tmp_path):
    server = fw.build_framework_server(
        root=tmp_path, include_agents=False, include_security=False, include_local_tools=False
    )
    result = server.call_tool("git_show", {})
    assert result["isError"] is True


# ── entry points ──────────────────────────────────────────────────────────
def test_serve_framework_calls_run_stdio(monkeypatch):
    recorded: dict[str, object] = {}

    class _FakeServer:
        def run_stdio(self) -> None:
            recorded["ran"] = True

    def fake_build(**kwargs):  # noqa: ANN003, ANN202
        recorded["kwargs"] = kwargs
        return _FakeServer()

    monkeypatch.setattr(fw, "build_framework_server", fake_build)
    fw.serve_framework(root="/tmp/x")
    assert recorded["ran"] is True
    assert recorded["kwargs"] == {"root": "/tmp/x"}


def test_main_entry_point(monkeypatch):
    mainmod = importlib.import_module("src.mcp.__main__")
    seen: dict[str, object] = {}
    monkeypatch.setattr(mainmod, "serve_framework", lambda **kw: seen.update(kw))
    assert mainmod.main(["/some/root"]) == 0
    assert seen == {"root": "/some/root"}
    assert mainmod.main([]) == 0
    assert seen == {"root": None}
