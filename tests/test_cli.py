"""Tests for src/cli/main.py — the unified `nexus` command surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import src.cli.main as cli
from src.sessions.manager import SessionManager
from src.skills.loader import SkillLoader

_REVIEW_SCRIPT = Path("/data/data/com.termux/files/usr/tmp/run_5_agents.py")
_REVIEW_DYN = Path("/data/data/com.termux/files/usr/tmp/review_dynamic.py")


class _FakeBackend:
    keys = ["k1", "k2"]
    models = ["m1", "m2"]


class _FakeResult:
    output = "ANSWER"


class _FakeAgent:
    def __init__(self, backend: Any = None) -> None:
        self.backend = backend

    def run(self, task: Any) -> _FakeResult:
        return _FakeResult()


@pytest.fixture
def isolated_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the CLI's managers at temp dirs and stub the network backend."""
    monkeypatch.setattr(cli, "SessionManager", lambda *a, **k: SessionManager(base_dir=tmp_path / "sessions"))
    monkeypatch.setattr(cli, "SkillLoader", lambda *a, **k: SkillLoader(base_dir=tmp_path / "skills"))
    import src.core.ollama_backend as ob

    monkeypatch.setattr(ob, "OllamaBackend", lambda *a, **k: _FakeBackend())


def test_cmd_status(isolated_cli: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_status(_ns()) == 0
    out = capsys.readouterr().out
    assert "Nexus-Core Status" in out
    assert "Backend: OllamaBackend" in out
    assert "Agents:" in out


def test_cmd_agents(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_agents(_ns()) == 0
    assert "وكيل" in capsys.readouterr().out


def test_cmd_ask(isolated_cli: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import src.agents.analyst as analyst_mod

    monkeypatch.setattr(analyst_mod, "AnalystAgent", _FakeAgent)
    assert cli.cmd_ask(_ns(question=["what", "is", "up"])) == 0
    assert "ANSWER" in capsys.readouterr().out


def test_cmd_ask_plain_result(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import src.agents.analyst as analyst_mod
    import src.core.ollama_backend as ob

    class PlainAgent:
        def __init__(self, backend: Any = None) -> None:
            pass

        def run(self, task: Any) -> str:
            return "RAW"

    monkeypatch.setattr(ob, "OllamaBackend", lambda *a, **k: _FakeBackend())
    monkeypatch.setattr(analyst_mod, "AnalystAgent", PlainAgent)
    assert cli.cmd_ask(_ns(question=["q"])) == 0
    assert "RAW" in capsys.readouterr().out


def test_cmd_chat_exit(isolated_cli: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import src.agents.analyst as a
    import src.agents.architect as ar
    import src.agents.coder as c
    import src.agents.reviewer as r

    for mod in (a, ar, c, r):
        for attr in ("AnalystAgent", "ArchitectAgent", "ReviewerAgent", "CoderAgent"):
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, _FakeAgent)

    inputs = iter(["hi there", "exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    assert cli.cmd_chat(_ns(agent="analyst")) == 0


def test_cmd_chat_eof(isolated_cli: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_eof(*a: Any) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert cli.cmd_chat(_ns(agent="analyst")) == 0


def test_cmd_review_missing_path(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert cli.cmd_review(_ns(path=str(tmp_path / "nope"))) == 1
    assert "غير موجود" in capsys.readouterr().out


def test_cmd_review_script_absent(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    # real target exists; the helper script does not → graceful failure
    assert cli.cmd_review(_ns(path=str(tmp_path))) == 1


def test_cmd_review_runs_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    had = _REVIEW_SCRIPT.exists()
    if not had:
        _REVIEW_SCRIPT.write_text('TARGET = Path("/data/x")\n', encoding="utf-8")
    try:
        calls: list[Any] = []
        monkeypatch.setattr("subprocess.call", lambda argv: calls.append(argv) or 0)
        assert cli.cmd_review(_ns(path=str(tmp_path))) == 0
        assert calls and calls[0][0] == "python3"
        assert _REVIEW_DYN.exists()
    finally:
        if not had:
            _REVIEW_SCRIPT.unlink(missing_ok=True)
        _REVIEW_DYN.unlink(missing_ok=True)


def test_cmd_sessions_empty_and_populated(
    isolated_cli: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert cli.cmd_sessions(_ns()) == 0
    assert "لا توجد جلسات" in capsys.readouterr().out
    sm = SessionManager(base_dir=tmp_path / "sessions")
    sm.create(title="t")
    assert cli.cmd_sessions(_ns()) == 0
    assert "جلسة" in capsys.readouterr().out


def test_cmd_skills(isolated_cli: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_skills(_ns()) == 0
    assert "مهارة" in capsys.readouterr().out


def test_cmd_skills_empty(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class EmptyLoader:
        def list_skills(self) -> list[str]:
            return []

    monkeypatch.setattr(cli, "SkillLoader", lambda *a, **k: EmptyLoader())
    assert cli.cmd_skills(_ns()) == 0
    assert "لا توجد مهارات" in capsys.readouterr().out


def test_cmd_status_lists_sessions_and_handles_backend_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.core.ollama_backend as ob

    monkeypatch.setattr(cli, "SessionManager", lambda *a, **k: SessionManager(base_dir=tmp_path / "sessions"))
    monkeypatch.setattr(cli, "SkillLoader", lambda *a, **k: SkillLoader(base_dir=tmp_path / "skills"))
    SessionManager(base_dir=tmp_path / "sessions").create(title="seed")

    def broken(*a: Any, **k: Any) -> Any:
        raise RuntimeError("no keys")

    monkeypatch.setattr(ob, "OllamaBackend", broken)
    assert cli.cmd_status(_ns()) == 0
    out = capsys.readouterr().out
    assert "seed" in out
    assert "Backend: ❌" in out


def test_cmd_chat_skips_empty_and_reports_agent_error(
    isolated_cli: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.agents.analyst as analyst_mod

    class BoomAgent:
        def __init__(self, backend: Any = None) -> None:
            pass

        def run(self, task: Any) -> Any:
            raise RuntimeError("boom")

    monkeypatch.setattr(analyst_mod, "AnalystAgent", BoomAgent)
    inputs = iter(["", "real question", "exit"])
    monkeypatch.setattr("builtins.input", lambda *a: next(inputs))
    assert cli.cmd_chat(_ns(agent="analyst")) == 0
    assert "boom" in capsys.readouterr().out


def test_cmd_skill_found_and_missing(isolated_cli: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_skill(_ns(name="code-review")) == 0
    assert "Code Review" in capsys.readouterr().out
    assert cli.cmd_skill(_ns(name="ghost")) == 1
    assert "غير موجودة" in capsys.readouterr().out


def test_cmd_delegate_unknown_agent(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_delegate(_ns(agent="does_not_exist", task=["t"])) == 1
    assert "غير موجود" in capsys.readouterr().out


def test_cmd_delegate_no_agent_class(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import sys
    import types

    fake = types.ModuleType("src.agents.nocls")
    setattr(fake, "helper", lambda: None)  # nothing ending in "Agent"
    monkeypatch.setitem(sys.modules, "src.agents.nocls", fake)
    assert cli.cmd_delegate(_ns(agent="nocls", task=["t"])) == 1
    assert "class Agent" in capsys.readouterr().out


def test_cmd_delegate_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import src.agents.analyst as analyst_mod
    import src.core.ollama_backend as ob

    monkeypatch.setattr(ob, "OllamaBackend", lambda *a, **k: _FakeBackend())
    monkeypatch.setattr(analyst_mod, "AnalystAgent", _FakeAgent)
    assert cli.cmd_delegate(_ns(agent="analyst", task=["do", "it"])) == 0
    assert "ANSWER" in capsys.readouterr().out


# ───────────────────────────── main() dispatch ─────────────────────────────

def _ns(**kw: Any) -> Any:
    import argparse

    return argparse.Namespace(**kw)


def test_main_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_main_version() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--version"])


def test_main_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def make(name: str) -> Any:
        def handler(args: Any) -> int:
            seen.append(name)
            return 0

        return handler

    for name in ("status", "agents", "ask", "chat", "sessions", "skills", "skill", "delegate", "review"):
        monkeypatch.setattr(cli, f"cmd_{name}", make(name))

    assert cli.main(["status"]) == 0
    assert seen == ["status"]
