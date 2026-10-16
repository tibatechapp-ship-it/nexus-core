"""Tests for src/agent_loop/* — ReAct loop + tool registry (offline)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent_loop.loop import SYSTEM_PROMPT, AgentLoop
from src.agent_loop.tools import Tool, ToolRegistry, build_default_registry


# ───────────────────────────── helpers ─────────────────────────────

class _FakeLLM:
    """Minimal stand-in for novamind's LLMRouter."""

    def __init__(self, providers: list[Any] | None = None) -> None:
        self.providers = providers or []


def _msg(content: str | None = None,
         tool_calls: list[Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tc(name: str, args: dict[str, Any] | str) -> SimpleNamespace:
    raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    return SimpleNamespace(id=f"id-{name}", type="function",
                           function=SimpleNamespace(name=name, arguments=raw))


class _ScriptedLoop(AgentLoop):
    """AgentLoop whose _call_llm replays a fixed script of messages."""

    def __init__(self, script: list[SimpleNamespace], **kw: Any) -> None:
        super().__init__(llm=_FakeLLM(), registry=kw.pop("registry", None) or build_default_registry(),
                         **kw)
        self._script = list(script)
        self.calls = 0

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if not self._script:
            # keep answering forever → exercises the max_iterations guard
            return {"ok": True,
                    "message": _msg(content="sto",
                                    tool_calls=[_tc("get_time", {})])}
        return {"ok": True, "message": self._script.pop(0)}


# ───────────────────────────── loop ─────────────────────────────

def test_system_prompt_mentions_react_steps() -> None:
    assert "فكر" in SYSTEM_PROMPT and "أجب" in SYSTEM_PROMPT


def test_loop_direct_answer() -> None:
    loop = _ScriptedLoop([_msg(content="جاهز")], verbose=False)
    r = loop.run("hi")
    assert r["ok"] is True and r["answer"] == "جاهز" and r["iterations"] == 1
    assert loop.trace[0]["text"].startswith("المهمة")


def test_loop_tool_then_answer(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    loop = _ScriptedLoop(
        [_msg(tool_calls=[_tc("write_file", {"path": str(target), "content": "abc"})]),
         _msg(content="تم")],
        verbose=False)
    r = loop.run("write it")
    assert r["ok"] is True and r["iterations"] == 2
    assert target.read_text(encoding="utf-8") == "abc"
    assert r["trace"][-1]["text"] == "الإجابة النهائية"
    assert any("write_file" in t["text"] for t in r["trace"])


def test_loop_bad_json_args_falls_back_to_empty() -> None:
    # arguments that are not valid JSON → args = {} → get_time runs with no args
    loop = _ScriptedLoop(
        [_msg(tool_calls=[_tc("get_time", "{broken")]), _msg(content="ok")],
        verbose=False)
    r = loop.run("time?")
    assert r["ok"] is True and r["iterations"] == 2
    assert any("get_time" in t["text"] for t in r["trace"])


def test_loop_unknown_tool_reports_error() -> None:
    loop = _ScriptedLoop(
        [_msg(tool_calls=[_tc("nope_tool", {})]), _msg(content="done")],
        verbose=False)
    r = loop.run("x")
    assert r["ok"] is True
    assert any("غير موجودة" in t["text"] for t in r["trace"])


def test_loop_llm_failure_short_circuits() -> None:
    class _Bad(_ScriptedLoop):
        def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
            return {"ok": False, "error": "boom"}

    r = _Bad([_msg()], verbose=False).run("x")
    assert r["ok"] is False and r["error"] == "boom" and r["iterations"] == 1


def test_loop_max_iterations_guard() -> None:
    loop = _ScriptedLoop([], max_iterations=2, verbose=False)  # empty script → loops
    r = loop.run("x")
    assert r["ok"] is False and r["error"] == "max_iterations_exceeded"
    assert r["iterations"] == 2


def test_loop_verbose_logging() -> None:
    loop = _ScriptedLoop([_msg(content="ok")], verbose=True)
    r = loop.run("hi")
    assert r["ok"] is True and len(r["trace"]) >= 2


def test_call_llm_no_enabled_groq_provider() -> None:
    loop = AgentLoop(llm=_FakeLLM(providers=[]), registry=build_default_registry(),
                     verbose=False)
    assert loop._call_llm([{"role": "user", "content": "x"}])["ok"] is False


def test_agent_loop_defaults_to_real_router() -> None:
    loop = AgentLoop(registry=build_default_registry(), verbose=False)
    assert loop.llm is not None
    assert loop.max_iterations == 8 and loop.verbose is False


def test_call_llm_success_with_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Groq:
        name = "groq_01"
        enabled = True
        api_key = "k"
        base_url = "http://localhost:1"
        models = {"fast": "m"}

    class _Other:  # non-groq first → exercises the loop continue branch
        name = "zai_01"
        enabled = True
        api_key = "k"
        base_url = "http://localhost:2"
        models = {}

    loop = AgentLoop(llm=_FakeLLM(providers=[_Other(), _Groq()]),
                     registry=build_default_registry(), verbose=False)

    seen: dict[str, Any] = {}

    class _Completions:
        def create(self, **kw: Any) -> Any:
            seen.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="ok-from-llm", tool_calls=None))])

    class _Client:
        chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr("openai.OpenAI", lambda **kw: _Client())
    out = loop._call_llm([{"role": "user", "content": "x"}])
    assert out["ok"] is True and out["message"].content == "ok-from-llm"
    assert seen["model"] == "m" and isinstance(seen["tools"], list) and seen["tools"]


def test_call_llm_provider_selection_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _P:
        name = "groq_01"
        enabled = True
        api_key = "k"
        base_url = "http://localhost:1"
        models = {"fast": "m"}

    loop = AgentLoop(llm=_FakeLLM(providers=[_P()]), registry=build_default_registry(),
                     verbose=False)

    # make the OpenAI client construction fail → covered except branch
    class _FakeOpenAI:
        def __init__(self, **kw: Any) -> None:
            raise RuntimeError("no network")

    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI, raising=False)
    out = loop._call_llm([{"role": "user", "content": "x"}])
    assert out["ok"] is False and "no network" in out["error"]


# ───────────────────────────── tools ─────────────────────────────

def test_tool_to_openai() -> None:
    t = Tool("n", "d", lambda: None, {"type": "object"})
    spec = t.to_openai()
    assert spec["type"] == "function" and spec["function"]["name"] == "n"


def test_registry_register_and_call() -> None:
    reg = ToolRegistry()

    @reg.register("double", "x2", {"type": "object"})
    def double(v: int) -> int:
        if not isinstance(v, int):
            raise TypeError("int expected")
        return v * 2

    assert reg.call("double", {"v": 3}) == "6"
    assert "غير موجودة" in reg.call("missing", {})
    assert reg.call("double", {"v": "x"}).startswith("خطأ")   # raised inside tool
    assert reg.call("double", {}).startswith("خطأ")            # missing argument
    assert len(reg.to_openai()) == 1


def test_default_registry_has_all_nine_tools() -> None:
    reg = build_default_registry()
    assert set(reg.tools) == {"search_memory", "remember", "list_agents", "run_agent",
                              "read_file", "get_time", "write_file", "list_files",
                              "run_shell"}


def test_tool_get_time_and_file_roundtrip(tmp_path: Path) -> None:
    reg = build_default_registry()
    f = tmp_path / "a" / "b.txt"
    assert "تم الكتابة" in reg.call("write_file", {"path": str(f), "content": "مرحبا"})
    assert reg.call("read_file", {"path": str(f)}) == "مرحبا"
    assert "مجلد غير موجود" in reg.call("list_files", {"directory": str(tmp_path / "nope")})
    assert "b.txt" in reg.call("list_files", {"directory": str(f.parent)})
    # null byte survives expanduser/expandvars → open() rejects it → except branch
    assert reg.call("write_file", {"path": "bad\x00name", "content": "x"}).startswith("خطأ")
    assert reg.call("get_time", {})[:4].isdigit()


def test_tool_read_file_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    reg = build_default_registry()
    assert "غير موجود" in reg.call("read_file", {"path": str(tmp_path / "x")})
    big = tmp_path / "big.bin"
    big.write_bytes(b"0" * 100_001)
    assert "كبير جدا" in reg.call("read_file", {"path": str(big)})

    # forced IO failure → both tools must degrade to a readable error
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists",
                        lambda p: (_ for _ in ()).throw(OSError("io")))
    assert reg.call("read_file", {"path": str(big)}).startswith("خطأ")
    monkeypatch.setattr(os.path, "exists", real_exists)

    assert "big.bin" in reg.call("list_files", {"directory": str(tmp_path)})
    assert "مجلد غير موجود" in reg.call("list_files",
                                        {"directory": str(tmp_path / "nope")})
    real_listdir = os.listdir
    monkeypatch.setattr(os, "listdir",
                        lambda p: (_ for _ in ()).throw(OSError("io")))
    assert reg.call("list_files", {"directory": str(tmp_path)}).startswith("خطأ")
    monkeypatch.setattr(os, "listdir", real_listdir)


def test_tool_memory_and_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.agent_rag_bridge as rag_mod

    reg = build_default_registry()

    class _Bridge:
        def recall(self, q: str, k: int = 3) -> list[Any]:
            return [SimpleNamespace(id="d1", text="تذكرة")]

        def remember(self, text: str) -> str:
            return "d-42"

    monkeypatch.setattr(rag_mod, "get_bridge", lambda: _Bridge())
    assert "تذكرة" in reg.call("search_memory", {"query": "q"})
    assert reg.call("remember", {"text": "hi"}) == "تم الحفظ: d-42"

    assert "عدد الوكلاء" in reg.call("list_agents", {})
    out = reg.call("list_agents", {"category": "code"})
    assert "فئة code" in out or "خطأ" in out
    # unknown agent → error string, not an exception
    assert reg.call("run_agent", {"agent": "__none__", "prompt": "x"}).startswith("خطأ")

    # memory tool failures must degrade to a readable error
    monkeypatch.setattr(rag_mod, "get_bridge", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert reg.call("search_memory", {"query": "q"}).startswith("خطأ")
    assert reg.call("remember", {"text": "hi"}).startswith("خطأ")


def test_tool_search_memory_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.memory.agent_rag_bridge as rag_mod

    class _Bridge:
        def recall(self, q: str, k: int = 3) -> list[Any]:
            return []

    monkeypatch.setattr(rag_mod, "get_bridge", lambda: _Bridge())
    assert build_default_registry().call("search_memory", {"query": "q"}) == "لا توجد نتائج"


def test_tool_run_agent_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import nova.registry as reg_mod

    class _Agent:
        def run(self, prompt: str) -> str:
            return f"ran {prompt}"

    class _NoMethod:
        pass

    class _Reg:
        def load_agent(self, name: str) -> Any:
            if name == "good":
                return _Agent()
            if name == "nomethod":
                return _NoMethod()
            raise KeyError(name)

    monkeypatch.setattr(reg_mod, "REGISTRY", _Reg())
    reg = build_default_registry()
    assert reg.call("run_agent", {"agent": "good", "prompt": "p"}) == "ran p"
    # an agent with no known method → readable message, not an exception
    assert "لا يملك طريقة" in reg.call("run_agent", {"agent": "nomethod", "prompt": "p"})
    # unknown agent → the except branch
    assert reg.call("run_agent", {"agent": "nope", "prompt": "p"}).startswith("خطأ")


def test_tool_agents_exception_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    import nova.registry as reg_mod

    reg = build_default_registry()
    monkeypatch.setattr(reg_mod, "agents_by_category",
                        lambda c: (_ for _ in ()).throw(RuntimeError("nope")))
    assert reg.call("list_agents", {"category": "code"}).startswith("خطأ")

    class _Reg:
        def load_agent(self, name: str) -> Any:
            raise RuntimeError("missing agent")

    monkeypatch.setattr(reg_mod, "REGISTRY", _Reg())
    assert reg.call("run_agent", {"agent": "x", "prompt": "y"}).startswith("خطأ")


def test_tool_run_shell_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = build_default_registry()
    assert "الأمر غير مسموح" in reg.call("run_shell", {"command": "rm -rf /"})
    assert "الأمر غير مسموح" in reg.call("run_shell", {"command": "  sudo ls"})
    out = reg.call("run_shell", {"command": "echo hi"})
    assert "hi" in out
    # subprocess failure → error branch
    import subprocess

    def _boom(*a: Any, **k: Any) -> Any:
        raise OSError("cannot exec")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert reg.call("run_shell", {"command": "echo hi"}).startswith("خطأ")
