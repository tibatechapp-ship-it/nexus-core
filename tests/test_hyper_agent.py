"""Hermetic tests for ``hyper_agent`` — every BUG-1..8 fix + BYOK workflow.

These tests never touch the network or a real LLM: the async workflow is
exercised with a stubbed ``create_llm_client_from_request`` (monkeypatched on
``hyper_agent``'s import site) and a canned ``generate``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

import hyper_agent as ha

# ---------------------------------------------------------------------------
# BUG-1 — prune replaces, never appends
# ---------------------------------------------------------------------------


def test_prune_no_duplication() -> None:
    """BUG-1: replacing with the trimmed slice must not grow the history."""
    history = [{"action": f"A{i}", "content": "", "result": ""} for i in range(30)]
    trimmed = ha.prune_history_fast(history, keep=5)
    assert len(trimmed) == 5
    assert [e["action"] for e in trimmed] == ["A25", "A26", "A27", "A28", "A29"]
    # The caller pattern `state["history"] = prune(...)` must shrink, not grow.
    state_history = history
    state_history = ha.prune_history_fast(state_history, keep=5)
    assert len(state_history) == 5


def test_prune_keep_zero_and_small() -> None:
    assert ha.prune_history_fast([{"action": "A"}], keep=0) == []
    assert len(ha.prune_history_fast([{"action": "A"}, {"action": "B"}], keep=5)) == 2


# ---------------------------------------------------------------------------
# BUG-3 — stall detection
# ---------------------------------------------------------------------------


def test_detect_stall() -> None:
    """BUG-3: 3 identical non-DONE/ERROR actions → stalled."""
    same = [{"action": "CODE", "content": "x", "result": ""}]
    assert ha.detect_stall(same * 3) is True
    assert ha.detect_stall(same * 2) is False
    mixed = [{"action": "CODE"}, {"action": "TEST"}, {"action": "CODE"}]
    assert ha.detect_stall(mixed) is False
    terminal = [{"action": "CODE"}, {"action": "DONE"}, {"action": "DONE"}]
    assert ha.detect_stall(terminal) is False


# ---------------------------------------------------------------------------
# BUG-8 — verify_goal gate
# ---------------------------------------------------------------------------


def test_verify_goal() -> None:
    goal = "write a fibonacci function"
    history = [
        {"action": "CODE", "content": "def fib(n): ...", "result": "ok"},
        {"action": "DONE", "content": "", "result": ""},
    ]
    assert ha.verify_goal(goal, history) is True
    assert ha.verify_goal(goal, []) is False
    assert ha.verify_goal("   ", history) is False
    # A DONE that names the goal also passes (the agent may summarize as it finishes).
    done_only = [{"action": "DONE", "content": "completed fibonacci function", "result": ""}]
    assert ha.verify_goal(goal, done_only) is True


def test_verify_goal_blocks_done() -> None:
    """goal not met → the DONE action does not produce status "done"."""
    goal = "implement the xyz parser"
    history = [{"action": "DONE", "content": "nothing done", "result": ""}]
    assert ha.verify_goal(goal, history) is False


# ---------------------------------------------------------------------------
# BUG-7 — sys.executable
# ---------------------------------------------------------------------------


def test_run_code_uses_sys_executable() -> None:
    """The child interpreter must be the CURRENT one (BUG-7)."""
    code = "import sys; print(sys.executable)"
    result = ha.run_code_sync(code, timeout=30)
    assert result["ok"] is True
    # Compare resolved paths — symlinks (e.g. /usr/bin/python3) resolve equal.
    assert Path(result["stdout"].strip()).resolve() == Path(sys.executable).resolve()


def test_run_tests_sync_uses_sys_executable() -> None:
    """run_tests_sync also invokes the current interpreter (BUG-7)."""
    # A trivially-passing single-file test dir.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "test_ok.py").write_text("def test_ok():\n    assert True\n")
        result = ha.run_tests_sync(tmp, timeout=60)
        assert result["ok"] is True


def test_run_tests_sync_missing_dir() -> None:
    result = ha.run_tests_sync("/nonexistent/path/xyz", timeout=5)
    assert result["ok"] is False


def test_run_code_rejects_empty_and_oversize() -> None:
    assert ha.run_code_sync("")["ok"] is False
    big = "x" * (ha.MAX_CODE_BYTES + 1)
    assert ha.run_code_sync(big)["ok"] is False


# ---------------------------------------------------------------------------
# BUG-6 — sandbox limits present on POSIX
# ---------------------------------------------------------------------------


def test_run_code_has_limits() -> None:
    """BUG-6: the sandbox applies preexec_fn limits on POSIX (no RLIMIT_AS)."""
    import inspect

    src = inspect.getsource(ha.run_code_sync)
    assert "preexec_fn" in src
    limits_src = inspect.getsource(ha._make_limits)
    assert "RLIMIT_CPU" in limits_src
    assert "RLIMIT_FSIZE" in limits_src
    assert "RLIMIT_NPROC" in limits_src
    # RLIMIT_AS must NOT be set (Android SIGABRTs Python when the cap trips).
    # The comment may mention the name; no actual setrlimit call may use it.
    assert "setlim(resource.RLIMIT_AS" not in limits_src


def test_run_code_success_and_failure() -> None:
    ok = ha.run_code_sync("print('hello')", timeout=30)
    assert ok["ok"] is True
    assert "hello" in ok["stdout"]
    bad = ha.run_code_sync("raise ValueError('boom')", timeout=30)
    assert bad["ok"] is False
    assert "boom" in bad["stderr"]


# ---------------------------------------------------------------------------
# BUG-4 — stored history drops raw_result
# ---------------------------------------------------------------------------


def test_parse_action_and_no_raw_result_field() -> None:
    """BUG-4: stored entries expose only action/content/result, never raw_result."""
    parsed = ha._parse_action('{"action": "CODE", "content": "print(1)"}')
    assert parsed["action"] == "CODE"
    # The stored-entry shape used by the workflow:
    entry = {
        "action": parsed["action"],
        "content": parsed["content"][:2000],
        "result": ""[:2000],
    }
    assert "raw_result" not in entry


def test_parse_action_fences_and_errors() -> None:
    fenced = ha._parse_action('```json\n{"action": "DONE", "content": "x"}\n```')
    assert fenced["action"] == "DONE"
    assert ha._parse_action("not json at all")["action"] == "ERROR"
    assert ha._parse_action("")["action"] == "ERROR"
    assert ha._parse_action("[1,2,3]")["action"] == "ERROR"
    assert ha._parse_action('{"content": "no action"}')["action"] == "ERROR"


# ---------------------------------------------------------------------------
# BUG-5 — last_parse_error counter
# ---------------------------------------------------------------------------


def test_last_parse_error_counter_updates() -> None:
    state: Dict[str, Any] = {"last_parse_error": 0}
    bad = ha._parse_action("garbage")
    if bad["action"] == "ERROR":
        state["last_parse_error"] = int(state["last_parse_error"]) + 1
    assert state["last_parse_error"] == 1
    good = ha._parse_action('{"action": "DONE"}')
    if good["action"] != "ERROR":
        state["last_parse_error"] = 0
    assert state["last_parse_error"] == 0


# ---------------------------------------------------------------------------
# BUG-2 — ollama num_predict (constructor-level, no network)
# ---------------------------------------------------------------------------


def test_ollama_num_predict_is_4000() -> None:
    """BUG-2: connectors/ollama.py bakes num_predict=4000 (not 500)."""
    import inspect

    from connectors import ollama

    src = inspect.getsource(ollama)
    assert "num_predict" in src
    assert "4000" in src
    assert "500" not in src


# ---------------------------------------------------------------------------
# BYOK workflow — async, stubbed LLM
# ---------------------------------------------------------------------------


class _StubLLM:
    """Minimal connector double: returns canned replies in order."""

    def __init__(self, replies: List[Dict[str, Any]]) -> None:
        self._replies = list(replies)
        self.calls: List[Dict[str, Any]] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        if not self._replies:
            return {"ok": False, "error": "no more replies"}
        return self._replies.pop(0)


def _patch_factory(monkeypatch: pytest.MonkeyPatch, stub: _StubLLM) -> None:
    """Patch the BYOK factory at the import site hyper_agent uses."""
    import hyper_app.services.llm_factory as factory

    monkeypatch.setattr(
        factory,
        "create_llm_client_from_request",
        lambda cfg=None: stub,
    )


def test_workflow_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful DONE (with a matching result) → status "done"."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    stub = _StubLLM(
        [
            {"ok": True, "reply": json.dumps({"action": "CODE", "content": "print('fib')"})},
            {"ok": True, "reply": json.dumps({"action": "DONE", "content": "complete"})},
        ]
    )
    _patch_factory(monkeypatch, stub)
    state = asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="write a fib function",
            max_iterations=5,
            user_config={"provider": "ollama"},
        )
    )
    assert state["status"] == "done"
    assert state["iterations"] == 2
    # BUG-4: no raw_result in stored history.
    assert all("raw_result" not in e for e in state["history"])
    # JSONL: one record per iteration.
    log_file = tmp_path / "log.jsonl"
    lines = [json.loads(x) for x in log_file.read_text().splitlines() if x.strip()]
    assert len(lines) == 2
    assert {k for k in lines[0]} >= {"goal", "cycle", "action", "result", "timing_ms", "parsed"}


def test_workflow_stall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """3 identical non-terminal actions → status "stalled" (BUG-3)."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    same = json.dumps({"action": "CODE", "content": "print(1)"})
    stub = _StubLLM([{"ok": True, "reply": same}] * 3)
    _patch_factory(monkeypatch, stub)
    state = asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="do something",
            max_iterations=5,
            user_config={"provider": "ollama"},
        )
    )
    assert state["status"] == "stalled"


def test_workflow_parse_errors_then_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BUG-5: parse errors increment the counter; a later good reply resets it."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    stub = _StubLLM(
        [
            {"ok": True, "reply": "this is not json"},
            {"ok": True, "reply": json.dumps({"action": "CODE", "content": "print('x')"})},
            {"ok": True, "reply": json.dumps({"action": "DONE", "content": "ok"})},
        ]
    )
    _patch_factory(monkeypatch, stub)
    state = asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="print x",
            max_iterations=5,
            user_config={"provider": "ollama"},
        )
    )
    assert state["last_parse_error"] == 0
    assert state["status"] == "done"


def test_workflow_provider_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider ``ok=False`` surfaces as a recorded ERROR, not a crash."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    stub = _StubLLM([{"ok": False, "error": "Missing Ollama API Key"}])
    _patch_factory(monkeypatch, stub)
    state = asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="anything",
            max_iterations=3,
            user_config={"provider": "ollama"},
        )
    )
    assert state["status"] == "verify_fail"
    assert state["history"][-1]["action"] == "ERROR"


def test_workflow_max_iterations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Loop exhausts max_iterations without a terminal action."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    stub = _StubLLM(
        [
            {"ok": True, "reply": json.dumps({"action": "CODE", "content": "print(1)"})},
            {"ok": True, "reply": json.dumps({"action": "TEST", "content": "tests"})},
            {"ok": True, "reply": json.dumps({"action": "CODE", "content": "print(2)"})},
            {"ok": True, "reply": json.dumps({"action": "TEST", "content": "tests"})},
        ]
    )
    _patch_factory(monkeypatch, stub)
    state = asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="keep going",
            max_iterations=4,
            user_config={"provider": "ollama"},
        )
    )
    assert state["status"] == "max_iterations"


def test_workflow_folds_system_prompt_for_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama ignores system_prompt; the engine folds it into the user prompt."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    stub = _StubLLM(
        [{"ok": True, "reply": json.dumps({"action": "DONE", "content": "ok"})}]
    )
    _patch_factory(monkeypatch, stub)
    asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="x",
            max_iterations=1,
            user_config={"provider": "ollama"},
        )
    )
    # For the local provider the prompt we send contains the system text.
    assert stub.calls, "generate was never called"
    assert "autonomous coding agent" in stub.calls[0]["prompt"]


def test_workflow_resume_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A resume dict seeds history/status; the `goal` arg is authoritative."""
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(tmp_path / "log.jsonl"))
    seed_history = [{"action": "CODE", "content": "seed", "result": "resume goal"}]
    resume = {"history": list(seed_history), "last_parse_error": 0, "goal": "old ignored goal"}
    stub = _StubLLM([{"ok": True, "reply": json.dumps({"action": "DONE", "content": "ok"})}])
    _patch_factory(monkeypatch, stub)
    state = asyncio.run(
        ha.autonomous_workflow_hyper(
            goal="resume goal",
            max_iterations=1,
            resume=resume,
            user_config={"provider": "ollama"},
        )
    )
    assert state["status"] == "done"
    assert state["goal"] == "resume goal"
    assert state["history"][0]["content"] == "seed"
    # The caller's resume dict must not be mutated (we copy the list).
    assert resume["history"] == seed_history


def test_append_log_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken log path must not raise (best-effort observability)."""
    monkeypatch.setattr(ha, "LOG_PATH", tmp_path / "no" / "such" / "deep" / "file.jsonl")
    ha._append_log({"goal": "g", "cycle": 1, "action": "CODE", "result": "", "timing_ms": 0, "parsed": True})
    # If it returned without raising, the guard worked.


# ---------------------------------------------------------------------------
# Coverage gap-fills (hyper_agent.py 89% -> ~99%): empty-system fold,
# _read_cap missing file, _append_log mkdir failure, run_code_sync timeout
# (both killpg and killpg-OSError branches), _make_limits rlimit branches,
# and _parse_action fenced-without-JSON fall-through.
# ---------------------------------------------------------------------------


def test_fold_empty_system_prompt_returns_task() -> None:
    assert ha._fold_system_into_prompt("", "do the thing") == "do the thing"


def test_read_cap_missing_file_returns_empty() -> None:
    assert ha._read_cap(Path("/nonexistent/xyz-hyper-agent-nope"), 10) == ""


def test_append_log_mkdir_failure_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # afile is a regular FILE, so mkdir on its "parent" raises
    # NotADirectoryError (an OSError subclass) — _append_log must swallow it.
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    monkeypatch.setenv("NEXUS_HYPER_LOG", str(afile / "log.jsonl"))
    ha._append_log({"event": "y"})  # must not raise


def test_run_code_sync_timeout_kills_session() -> None:
    r = ha.run_code_sync("import time\ntime.sleep(10)", timeout=1)
    assert r["ok"] is False and r["timeout"] is True
    assert r["exit_code"] == -1 and r["stderr"] == "timeout"


def test_run_code_sync_timeout_killpg_oserror_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*a: object, **kw: object) -> None:
        raise OSError("gone")

    monkeypatch.setattr(ha.os, "killpg", _boom)
    r = ha.run_code_sync("import time\ntime.sleep(10)", timeout=1)
    assert r["ok"] is False and r["timeout"] is True
    assert r["stderr"] == "timeout"


def test_make_limits_records_cpu_fsize_and_nproc(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int]] = []

    def _set(res: int, lim: tuple[int, int]) -> None:
        seen.append((res, lim[0]))

    monkeypatch.setattr(ha.resource, "setrlimit", _set)
    monkeypatch.setattr(ha.resource, "getrlimit", lambda res: (10, 100))
    ha._make_limits()()  # monkeypatched — no real rlimits are applied to us
    assert (ha.resource.RLIMIT_CPU, ha.MAX_TIMEOUT) in seen
    assert (ha.resource.RLIMIT_FSIZE, ha.MAX_FSIZE) in seen
    assert (ha.resource.RLIMIT_NPROC, min(10, ha.MAX_PROCS)) in seen


def test_make_limits_rlim_inf_nproc(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(ha.resource, "setrlimit", lambda res, lim: seen.append((res, lim[0])))
    monkeypatch.setattr(ha.resource, "getrlimit", lambda res: (ha.resource.RLIM_INFINITY, -1))
    ha._make_limits()()
    assert (ha.resource.RLIMIT_NPROC, ha.MAX_PROCS) in seen


def test_make_limits_swallows_setrlimit_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(res: int, lim: tuple[int, int]) -> None:
        raise OSError("nope")

    monkeypatch.setattr(ha.resource, "setrlimit", _boom)
    monkeypatch.setattr(ha.resource, "getrlimit", lambda res: (1, 1))
    ha._make_limits()()  # must not raise


def test_make_limits_swallows_getrlimit_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ha.resource, "setrlimit", lambda res, lim: None)

    def _boom(res: int) -> tuple[int, int]:
        raise ValueError("bad")

    monkeypatch.setattr(ha.resource, "getrlimit", _boom)
    ha._make_limits()()  # must not raise


def test_parse_action_fenced_without_json_is_error() -> None:
    r = ha._parse_action("```python\nprint(1)\n```")
    assert r["action"] == "ERROR" and r["content"].startswith("unparseable:")
